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

        return [{"segment": step_id, "prior": 1.0, "current": 2.0, "changeBps": 10.0, "contribution": 0.5}]

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql)
    plan = [
        QueryPlanStep(id="step-a", goal="Goal A"),
        QueryPlanStep(id="step-b", goal="Goal B"),
        QueryPlanStep(id="step-c", goal="Goal C"),
    ]

    original_parallel_limit = settings.real_max_parallel_queries
    original_provider_mode_raw = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "real_max_parallel_queries", 2)
        outcome = await stage.run_sql(message="run parallel query steps", plan=plan, history=[])
    finally:
        object.__setattr__(settings, "real_max_parallel_queries", original_parallel_limit)
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert peak_active_calls > 1
    assert [row.rows[0]["segment"] for row in outcome.results] == ["step-a", "step-b", "step-c"]
    assert outcome.assumptions == ["assumption for step-a", "assumption for step-b", "assumption for step-c"]


@pytest.mark.asyncio
async def test_sql_stage_does_not_run_hardcoded_repair_queries() -> None:
    model = load_semantic_model()
    executed_sql: list[str] = []

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "generationType": "sql_ready",
            "sql": "SELECT transaction_state, SUM(spend) AS total_spend FROM cia_sales_insights_cortex GROUP BY transaction_state",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        executed_sql.append(sql)
        return [{"transaction_state": "TX", "total_spend": 100.0}]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    outcome = await stage.run_sql(
        message="Show me sales by state",
        plan=[QueryPlanStep(id="step-1", goal="Show state sales")],
        history=[],
    )

    assert outcome.results
    assert outcome.results[0].rows[0]["transaction_state"] == "TX"
    assert len(executed_sql) == 1
    assert not any("Auto-repaired SQL output" in item for item in outcome.assumptions)


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

    outcome = await stage.run_sql(
        message="what were my total sales for last month",
        plan=[QueryPlanStep(id="step-1", goal=planner_task)],
        history=[],
        conversation_id="conv-verbatim",
    )

    assert outcome.results
    assert analyst_messages == [planner_task]
    assert "Global user request" not in analyst_messages[0]
    assert "Respond with SQL" not in analyst_messages[0]


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
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        outcome = await stage.run_sql(message="run independent query steps", plan=plan, history=[])
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert peak_active_calls > 1
    assert [row.rows[0]["segment"] for row in outcome.results] == ["step-a", "step-b", "step-c"]


@pytest.mark.asyncio
async def test_sql_stage_blocks_execution_above_five_steps() -> None:
    model = load_semantic_model()

    async def fake_sql(_: str) -> list[dict[str, object]]:
        return []

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id=f"step-{index}", goal=f"Goal {index}") for index in range(1, 7)]

    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await stage.run_sql(message="Run many steps", plan=plan, history=[])

    assert "exceeds the governed limit" in blocked.value.user_message.lower()
