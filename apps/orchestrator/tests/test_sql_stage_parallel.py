from __future__ import annotations

import asyncio
import re

import pytest

from app.config import settings
from app.models import QueryPlanStep
from app.services.semantic_model import load_semantic_model
from app.services.stages.sql_stage import SqlExecutionStage, SqlGenerationBlockedError


async def _fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
    user_prompt = str(kwargs.get("user_prompt", ""))
    match = re.search(r"Step id:\s*(step-[a-z])", user_prompt, flags=re.IGNORECASE)
    step_id = match.group(1).lower() if match else "step-x"
    return {
        "sql": (
            f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
            "FROM cia_sales_insights_cortex LIMIT 1"
        ),
        "assumptions": [f"assumption for {step_id}"],
    }


@pytest.mark.asyncio
async def test_parallel_sql_execution_preserves_plan_order() -> None:
    model = load_semantic_model()
    delays = {"step-a": 0.15, "step-b": 0.03, "step-c": 0.08}
    active_calls = 0
    peak_active_calls = 0
    lock = asyncio.Lock()

    async def fake_sql(sql: str) -> list[dict[str, float | str]]:
        nonlocal active_calls, peak_active_calls
        match = re.search(r"'(step-[a-z])'\s+AS\s+segment", sql, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"

        async with lock:
            active_calls += 1
            peak_active_calls = max(peak_active_calls, active_calls)

        await asyncio.sleep(delays.get(step_id, 0.01))

        async with lock:
            active_calls -= 1

        return [
            {"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql)
    plan = [
        QueryPlanStep(id="step-a", goal="Goal A"),
        QueryPlanStep(id="step-b", goal="Goal B"),
        QueryPlanStep(id="step-c", goal="Goal C"),
    ]

    original_parallel_limit = settings.real_max_parallel_queries
    original_provider_mode_raw = settings.provider_mode_raw
    original_use_mock_providers = settings.use_mock_providers
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "use_mock_providers", False)
        object.__setattr__(settings, "real_max_parallel_queries", 2)
        results, assumptions = await stage.run_sql(
            message="run parallel query steps",
            plan=plan,
            history=[],
        )
    finally:
        object.__setattr__(settings, "real_max_parallel_queries", original_parallel_limit)
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)
        object.__setattr__(settings, "use_mock_providers", original_use_mock_providers)

    assert peak_active_calls > 1
    assert [row.rows[0]["segment"] for row in results] == ["step-a", "step-b", "step-c"]
    assert assumptions == [
        "assumption for step-a",
        "assumption for step-b",
        "assumption for step-c",
    ]


@pytest.mark.asyncio
async def test_sql_stage_does_not_run_hardcoded_repair_queries() -> None:
    model = load_semantic_model()
    executed_sql: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "generationType": "sql_ready",
            "sql": (
                "SELECT transaction_state, SUM(spend) AS total_spend "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        executed_sql.append(sql)
        return [{"transaction_state": "TX", "total_spend": 100.0}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Show state sales")]

    results, assumptions = await stage.run_sql(
        message="Show me sales by state",
        plan=plan,
        history=[],
    )

    assert results
    assert results[0].rows[0]["transaction_state"] == "TX"
    assert len(executed_sql) == 1
    assert not any("Auto-repaired SQL output" in item for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_raises_clarification_when_analyst_requests_it() -> None:
    model = load_semantic_model()
    analyst_calls = 0

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal analyst_calls
        _ = kwargs
        analyst_calls += 1
        return {
            "type": "clarification",
            "clarificationQuestion": "Which metric and time window should I use?",
            "clarificationKind": "user_input_required",
            "failedSql": "SELECT SUM(spend) FROM bad_schema.bad_table",
            "assumptions": ["user intent is broad"],
        }

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [QueryPlanStep(id="step-1", goal="Analyze performance")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="Analyze performance",
            plan=plan,
            history=[],
            conversation_id="conv-clarify",
        )

    assert blocked.value.stop_reason == "clarification"
    assert "Which metric and time window" in blocked.value.user_message
    assert "bad_schema.bad_table" in str(blocked.value.detail.get("failedSql", ""))
    assert blocked.value.detail.get("clarificationKind") == "user_input_required"
    assert analyst_calls == 1


@pytest.mark.asyncio
async def test_sql_stage_retries_generation_technical_failure_until_retry_limit() -> None:
    model = load_semantic_model()
    analyst_calls = 0
    seen_retry_feedback: list[list[dict[str, object]]] = []

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal analyst_calls
        analyst_calls += 1
        seen_retry_feedback.append(list(kwargs.get("retry_feedback", []) or []))
        return {
            "type": "clarification",
            "clarificationQuestion": "SQL generation failed: model returned sql_ready without executable SQL.",
            "clarificationKind": "technical_failure",
            "assumptions": [],
        }

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [QueryPlanStep(id="step-1", goal="Calculate total spend")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=plan,
            history=[],
            conversation_id="conv-generation-tech-failure",
        )

    assert analyst_calls >= 2
    assert len(seen_retry_feedback) == analyst_calls
    assert seen_retry_feedback[0] == []
    assert len(seen_retry_feedback[-1]) >= 1
    assert blocked.value.stop_reason == "clarification"
    assert "technical error" in blocked.value.user_message.lower() or "failed" in blocked.value.user_message.lower()
    retry_feedback = blocked.value.detail.get("retryFeedback") or []
    assert isinstance(retry_feedback, list)
    assert len(retry_feedback) >= 1


@pytest.mark.asyncio
async def test_sql_stage_surfaces_execution_timeout_without_generation_retry() -> None:
    model = load_semantic_model()
    sql_calls = 0

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "generationType": "sql_ready",
            "sql": "SELECT transaction_state FROM cia_sales_insights_cortex LIMIT 1",
            "assumptions": [],
        }

    async def fake_sql(_: str) -> list[dict[str, object]]:
        nonlocal sql_calls
        sql_calls += 1
        raise TimeoutError("query timed out")

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Show one row")]

    original_sla = settings.sql_step_sla_seconds
    try:
        object.__setattr__(settings, "sql_step_sla_seconds", 120.0)
        with pytest.raises(SqlGenerationBlockedError) as blocked:
            await stage.run_sql(
                message="Show one row",
                plan=plan,
                history=[],
            )
    finally:
        object.__setattr__(settings, "sql_step_sla_seconds", original_sla)

    assert sql_calls == 1
    assert blocked.value.detail.get("errorCode") == "execution_timeout"
    retry_feedback = blocked.value.detail.get("retryFeedback") or []
    assert retry_feedback
    assert retry_feedback[-1].get("errorCode") == "execution_timeout"


@pytest.mark.asyncio
async def test_sql_stage_removes_clarification_text_from_assumptions() -> None:
    model = load_semantic_model()

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "type": "clarification",
            "clarificationQuestion": "Which metric should I use?",
            "clarificationKind": "user_input_required",
            "assumptions": ["Which metric should I use?"],
        }

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [QueryPlanStep(id="step-1", goal="Analyze performance")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="Analyze performance",
            plan=plan,
            history=[],
            conversation_id="conv-assumption-dedupe",
        )

    assumptions = blocked.value.detail.get("assumptions") or []
    assert all(str(item).strip().lower() != "which metric should i use?" for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_passes_planner_task_verbatim_to_analyst() -> None:
    model = load_semantic_model()
    analyst_messages: list[str] = []

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return [{"segment": "total_sales", "prior": 0.0, "current": 1.0, "changeBps": 0.0, "contribution": 1.0}]

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        analyst_messages.append(str(kwargs.get("message", "")))
        return {
            "type": "sql_ready",
            "sql": (
                "SELECT 'total_sales' AS segment, 0.0 AS prior, 1.0 AS current, 0.0 AS changeBps, 1.0 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [],
        }

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    planner_task = "Calculate the total sales for last month. Return the aggregate sales amount for the complete prior calendar month."
    plan = [QueryPlanStep(id="step-1", goal=planner_task)]

    results, _ = await stage.run_sql(
        message="what were my total sales for last month",
        plan=plan,
        history=[],
        conversation_id="conv-verbatim",
    )

    assert results
    assert analyst_messages == [planner_task]
    assert "Global user request" not in analyst_messages[0]
    assert "Respond with SQL" not in analyst_messages[0]


@pytest.mark.asyncio
async def test_sql_stage_raises_not_relevant_when_analyst_flags_out_of_scope() -> None:
    model = load_semantic_model()

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "type": "not_relevant",
            "notRelevantReason": "Outside semantic model scope.",
            "assumptions": ["question appears unrelated"],
        }

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [QueryPlanStep(id="step-1", goal="Answer weather question")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is the weather today?",
            plan=plan,
            history=[],
            conversation_id="conv-irrelevant",
        )

    assert blocked.value.stop_reason == "not_relevant"


@pytest.mark.asyncio
async def test_sql_stage_respects_serial_dependencies() -> None:
    model = load_semantic_model()
    execution_order: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        user_prompt = str(kwargs.get("user_prompt", ""))
        match = re.search(r"Step id:\s*(step-[0-9]+)", user_prompt, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        return {
            "generationType": "sql_ready",
            "sql": (
                f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [f"assumption for {step_id}"],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        match = re.search(r"'(step-[0-9]+)'\s+AS\s+segment", sql, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        execution_order.append(step_id)
        await asyncio.sleep(0.02)
        return [{"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [
        QueryPlanStep(id="step-1", goal="Compute top stores"),
        QueryPlanStep(id="step-2", goal="Compute mix for top stores", dependsOn=["step-1"], independent=False),
    ]

    original_provider_mode_raw = settings.provider_mode_raw
    original_use_mock_providers = settings.use_mock_providers
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "use_mock_providers", False)
        await stage.run_sql(
            message="Top stores and then repeat/new mix",
            plan=plan,
            history=[],
        )
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)
        object.__setattr__(settings, "use_mock_providers", original_use_mock_providers)

    assert execution_order[:2] == ["step-1", "step-2"]


@pytest.mark.asyncio
async def test_sql_stage_resolves_textual_depends_on_references() -> None:
    model = load_semantic_model()
    execution_order: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        user_prompt = str(kwargs.get("user_prompt", ""))
        match = re.search(r"Step id:\s*(step-[0-9]+)", user_prompt, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        return {
            "generationType": "sql_ready",
            "sql": (
                f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        match = re.search(r"'(step-[0-9]+)'\s+AS\s+segment", sql, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        execution_order.append(step_id)
        await asyncio.sleep(0.01)
        return [{"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [
        QueryPlanStep(id="step-1", goal="Identify top and bottom stores"),
        QueryPlanStep(
            id="step-2",
            goal="Show new vs repeat mix for those stores",
            dependsOn=["Identify top and bottom stores"],
            independent=False,
        ),
        QueryPlanStep(
            id="step-3",
            goal="Compare the same mix to last year",
            dependsOn=["task 2"],
            independent=False,
        ),
    ]

    original_provider_mode_raw = settings.provider_mode_raw
    original_use_mock_providers = settings.use_mock_providers
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "use_mock_providers", False)
        await stage.run_sql(
            message="top and bottom stores with new vs repeat mix and last year comparison",
            plan=plan,
            history=[],
        )
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)
        object.__setattr__(settings, "use_mock_providers", original_use_mock_providers)

    assert execution_order[:3] == ["step-1", "step-2", "step-3"]


@pytest.mark.asyncio
async def test_sql_stage_parallel_dispatch_on_prod_target() -> None:
    model = load_semantic_model()
    delays = {"step-a": 0.15, "step-b": 0.03, "step-c": 0.08}
    active_calls = 0
    peak_active_calls = 0
    lock = asyncio.Lock()

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        user_prompt = str(kwargs.get("user_prompt", ""))
        match = re.search(r"Step id:\s*(step-[a-z])", user_prompt, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        return {
            "generationType": "sql_ready",
            "sql": (
                f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [f"assumption for {step_id}"],
        }

    async def fake_sql(sql: str) -> list[dict[str, float | str]]:
        nonlocal active_calls, peak_active_calls
        match = re.search(r"'(step-[a-z])'\s+AS\s+segment", sql, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-x"
        async with lock:
            active_calls += 1
            peak_active_calls = max(peak_active_calls, active_calls)
        await asyncio.sleep(delays.get(step_id, 0.01))
        async with lock:
            active_calls -= 1
        return [{"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [
        QueryPlanStep(id="step-a", goal="Goal A"),
        QueryPlanStep(id="step-b", goal="Goal B"),
        QueryPlanStep(id="step-c", goal="Goal C"),
    ]

    original_provider_mode_raw = settings.provider_mode_raw
    original_use_mock_providers = settings.use_mock_providers
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "use_mock_providers", False)
        results, _ = await stage.run_sql(
            message="run independent query steps",
            plan=plan,
            history=[],
        )
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)
        object.__setattr__(settings, "use_mock_providers", original_use_mock_providers)

    assert peak_active_calls > 1
    assert [row.rows[0]["segment"] for row in results] == ["step-a", "step-b", "step-c"]


@pytest.mark.asyncio
async def test_sql_stage_retries_analyst_generation_without_llm_fallback() -> None:
    model = load_semantic_model()
    analyst_calls = 0
    llm_calls = 0

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal analyst_calls
        _ = kwargs
        analyst_calls += 1
        if analyst_calls == 1:
            return {
                "type": "clarification",
                "clarificationQuestion": "SQL generation failed: model returned sql_ready without executable SQL.",
                "clarificationKind": "technical_failure",
                "assumptions": [],
            }
        return {
            "type": "sql_ready",
            "sql": (
                "SELECT 'step-1' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [],
        }

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal llm_calls
        llm_calls += 1
        user_prompt = str(kwargs.get("user_prompt", ""))
        match = re.search(r"Step id:\s*(step-[0-9]+)", user_prompt, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-1"
        return {
            "generationType": "sql_ready",
            "sql": (
                f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
                "FROM cia_sales_insights_cortex LIMIT 1"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        match = re.search(r"'(step-[0-9]+)'\s+AS\s+segment", sql, flags=re.IGNORECASE)
        step_id = match.group(1).lower() if match else "step-1"
        return [{"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [QueryPlanStep(id="step-1", goal="Identify top and bottom stores")]

    results, assumptions = await stage.run_sql(
        message="Identify top and bottom stores",
        plan=plan,
        history=[],
        conversation_id="conv-analyst-retry",
    )

    assert analyst_calls == 2
    assert llm_calls == 0
    assert results
    assert results[0].rows[0]["segment"] == "step-1"
    assert any("SQL generation retry 1 failed" in item for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_retries_generation_after_execution_failure() -> None:
    model = load_semantic_model()
    llm_calls = 0
    sql_calls: list[str] = []
    user_prompts: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal llm_calls
        user_prompts.append(str(kwargs.get("user_prompt", "")))
        llm_calls += 1
        if llm_calls == 1:
            return {
                "generationType": "sql_ready",
                "sql": "SELECT SUM(spend) AS total_spend FROM cia_sales_insights_cortex WHERE bogus_col = 1",
                "assumptions": [],
            }
        return {
            "generationType": "sql_ready",
            "sql": "SELECT SUM(spend) AS total_spend FROM cia_sales_insights_cortex",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        sql_calls.append(sql)
        if len(sql_calls) == 1:
            raise RuntimeError("invalid identifier BOGUS_COL")
        return [{"total_spend": 123.45}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Calculate total spend")]

    results, assumptions = await stage.run_sql(
        message="What is my total spend?",
        plan=plan,
        history=[],
    )

    assert llm_calls == 2
    assert len(sql_calls) == 2
    assert results
    assert results[0].rows[0]["total_spend"] == 123.45
    assert "bogus_col" not in results[0].sql.lower()
    assert len(user_prompts) == 2
    assert "Retry feedback from prior SQL execution attempts" in user_prompts[1]
    assert "invalid identifier BOGUS_COL" in user_prompts[1]
    assert any("SQL execution retry 1 failed" in item for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_execution_failure_does_not_request_user_clarification_before_exhausting_retries() -> None:
    model = load_semantic_model()
    llm_calls = 0

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal llm_calls
        _ = kwargs
        llm_calls += 1
        if llm_calls == 1:
            return {
                "generationType": "sql_ready",
                "sql": "SELECT SUM(spend) AS total_spend FROM cia_sales_insights_cortex WHERE bogus_col = 1",
                "assumptions": [],
            }
        return {
            "generationType": "clarification",
            "clarificationQuestion": "Which metric and time window should I use?",
            "assumptions": [],
        }

    async def fake_sql(_: str) -> list[dict[str, object]]:
        raise RuntimeError("invalid identifier BOGUS_COL")

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Calculate total spend")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=plan,
            history=[],
    )

    assert blocked.value.stop_reason == "clarification"
    assert "which metric and time window should i use" in blocked.value.user_message.lower()
    assert llm_calls == 2
    retry_feedback = blocked.value.detail.get("retryFeedback")
    assert isinstance(retry_feedback, list)
    assert any(str(item.get("phase", "")).strip() == "sql_execution" for item in retry_feedback if isinstance(item, dict))


@pytest.mark.asyncio
async def test_sql_stage_retries_when_sql_returns_all_null_rows() -> None:
    model = load_semantic_model()
    llm_calls = 0
    sql_calls: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal llm_calls
        _ = kwargs
        llm_calls += 1
        if llm_calls == 1:
            return {
                "generationType": "sql_ready",
                "sql": "SELECT SUM(spend) AS total_sales, MIN(resp_date) AS data_from FROM cia_sales_insights_cortex",
                "assumptions": [],
            }
        return {
            "generationType": "sql_ready",
            "sql": "SELECT SUM(spend) AS total_sales, MAX(resp_date) AS data_through FROM cia_sales_insights_cortex",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        sql_calls.append(sql)
        if len(sql_calls) == 1:
            return [{"total_sales": None, "data_from": None}]
        return [{"total_sales": 123.45, "data_through": "2025-11-30"}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Calculate total sales")]

    results, assumptions = await stage.run_sql(
        message="What is my total sales?",
        plan=plan,
        history=[],
    )

    assert llm_calls == 2
    assert len(sql_calls) == 2
    assert results[0].rows[0]["total_sales"] == 123.45
    assert any("only null values" in item.lower() for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_exhausts_execution_retries_when_bad_sql_repeats() -> None:
    model = load_semantic_model()
    llm_calls = 0
    sql_calls = 0

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal llm_calls
        _ = kwargs
        llm_calls += 1
        return {
            "generationType": "sql_ready",
            "sql": "SELECT SUM(spend) AS total_spend FROM cia_sales_insights_cortex WHERE bogus_col = 1",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        nonlocal sql_calls
        sql_calls += 1
        if "bogus_col" in sql.lower():
            raise RuntimeError("invalid identifier BOGUS_COL")
        return [{"total_spend": 555.0}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Calculate total spend")]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=plan,
            history=[],
        )

    assert llm_calls == 3
    assert sql_calls == 3
    assert blocked.value.detail.get("phase") == "sql_execution"
    retry_feedback = blocked.value.detail.get("retryFeedback") or []
    assert len(retry_feedback) == 3
    assert all(str(item.get("phase", "")).strip() == "sql_execution" for item in retry_feedback)


@pytest.mark.asyncio
async def test_sql_stage_blocks_execution_above_five_steps() -> None:
    model = load_semantic_model()

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id=f"step-{index}", goal=f"Goal {index}") for index in range(1, 7)]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="Run many steps",
            plan=plan,
            history=[],
        )

    assert "exceeds the governed limit" in blocked.value.user_message.lower()
