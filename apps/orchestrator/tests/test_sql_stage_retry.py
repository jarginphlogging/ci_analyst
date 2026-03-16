from __future__ import annotations

import re

import pytest

from app.config import settings
from app.models import QueryPlanStep, TemporalScope
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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="Analyze performance",
            plan=[QueryPlanStep(id="step-1", goal="Analyze performance")],
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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=[QueryPlanStep(id="step-1", goal="Calculate total spend")],
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

    original_sla = settings.sql_step_sla_seconds
    try:
        object.__setattr__(settings, "sql_step_sla_seconds", 120.0)
        with pytest.raises(SqlGenerationBlockedError) as blocked:
            await stage.run_sql(
                message="Show one row",
                plan=[QueryPlanStep(id="step-1", goal="Show one row")],
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
async def test_sql_stage_retries_on_temporal_scope_mismatch_for_last_6_months() -> None:
    model = load_semantic_model()
    ask_calls = 0

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal ask_calls
        _ = kwargs
        ask_calls += 1
        if ask_calls == 1:
            return {
                "generationType": "sql_ready",
                "sql": "SELECT 'bad' AS version, RESP_DATE AS month_start FROM cia_sales_insights_cortex LIMIT 7",
                "assumptions": [],
            }
        return {
            "generationType": "sql_ready",
            "sql": "SELECT 'good' AS version, RESP_DATE AS month_start FROM cia_sales_insights_cortex LIMIT 6",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        if "'bad'" in sql:
            return [
                {"month_start": "2025-06-01", "customer_type": "new", "customers": 10},
                {"month_start": "2025-07-01", "customer_type": "new", "customers": 11},
                {"month_start": "2025-08-01", "customer_type": "new", "customers": 12},
                {"month_start": "2025-09-01", "customer_type": "new", "customers": 13},
                {"month_start": "2025-10-01", "customer_type": "new", "customers": 14},
                {"month_start": "2025-11-01", "customer_type": "new", "customers": 15},
                {"month_start": "2025-12-01", "customer_type": "new", "customers": 16},
            ]
        return [
            {"month_start": "2025-07-01", "customer_type": "new", "customers": 11},
            {"month_start": "2025-08-01", "customer_type": "new", "customers": 12},
            {"month_start": "2025-09-01", "customer_type": "new", "customers": 13},
            {"month_start": "2025-10-01", "customer_type": "new", "customers": 14},
            {"month_start": "2025-11-01", "customer_type": "new", "customers": 15},
            {"month_start": "2025-12-01", "customer_type": "new", "customers": 16},
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    outcome = await stage.run_sql(
        message="Show new vs repeat customers by month for the last 6 months.",
        plan=[QueryPlanStep(id="step-1", goal="Show new vs repeat customers by month for the last 6 months.")],
        history=[],
        temporal_scope=TemporalScope(unit="month", count=6, granularity="month"),
    )

    assert ask_calls == 2
    assert outcome.results[0].rowCount == 6


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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="Analyze performance",
            plan=[QueryPlanStep(id="step-1", goal="Analyze performance")],
            history=[],
            conversation_id="conv-assumption-dedupe",
        )

    assumptions = blocked.value.detail.get("assumptions") or []
    assert all(str(item).strip().lower() != "which metric should i use?" for item in assumptions)


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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is the weather today?",
            plan=[QueryPlanStep(id="step-1", goal="Answer weather question")],
            history=[],
            conversation_id="conv-irrelevant",
        )

    assert blocked.value.stop_reason == "not_relevant"


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
    outcome = await stage.run_sql(
        message="Identify top and bottom stores",
        plan=[QueryPlanStep(id="step-1", goal="Identify top and bottom stores")],
        history=[],
        conversation_id="conv-analyst-retry",
    )

    assert analyst_calls == 2
    assert llm_calls == 0
    assert outcome.results
    assert outcome.results[0].rows[0]["segment"] == "step-1"
    assert stage.latest_retry_feedback
    assert stage.latest_retry_feedback[-1].get("phase") == "sql_generation"


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
    outcome = await stage.run_sql(
        message="What is my total spend?",
        plan=[QueryPlanStep(id="step-1", goal="Calculate total spend")],
        history=[],
    )

    assert llm_calls == 2
    assert len(sql_calls) == 2
    assert outcome.results
    assert outcome.results[0].rows[0]["total_spend"] == 123.45
    assert "bogus_col" not in outcome.results[0].sql.lower()
    assert len(user_prompts) == 2
    assert "Retry feedback" in user_prompts[1]
    assert "invalid identifier BOGUS_COL" in user_prompts[1]
    assert stage.latest_retry_feedback
    assert stage.latest_retry_feedback[-1].get("phase") == "sql_execution"
    assert "BOGUS_COL" in str(stage.latest_retry_feedback[-1].get("error", ""))


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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=[QueryPlanStep(id="step-1", goal="Calculate total spend")],
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
    outcome = await stage.run_sql(
        message="What is my total sales?",
        plan=[QueryPlanStep(id="step-1", goal="Calculate total sales")],
        history=[],
    )

    assert llm_calls == 2
    assert len(sql_calls) == 2
    assert outcome.results[0].rows[0]["total_sales"] == 123.45
    assert stage.latest_retry_feedback
    assert stage.latest_retry_feedback[-1].get("errorCode") == "execution_all_null_rows"


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

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(
            message="What is my total spend?",
            plan=[QueryPlanStep(id="step-1", goal="Calculate total spend")],
            history=[],
        )

    assert llm_calls == 3
    assert sql_calls == 3
    assert blocked.value.detail.get("phase") == "sql_execution"
    retry_feedback = blocked.value.detail.get("retryFeedback") or []
    assert len(retry_feedback) == 3
    assert all(str(item.get("phase", "")).strip() == "sql_execution" for item in retry_feedback)
