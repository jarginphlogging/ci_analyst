from __future__ import annotations

import asyncio
import re

import pytest

from app.config import settings
from app.models import QueryPlanStep
from app.services.semantic_model import load_semantic_model
from app.services.stages.sql_stage import SqlExecutionStage


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

    original_parallel_enabled = settings.real_enable_parallel_sql
    original_parallel_limit = settings.real_max_parallel_queries
    try:
        object.__setattr__(settings, "real_enable_parallel_sql", True)
        object.__setattr__(settings, "real_max_parallel_queries", 2)
        results, assumptions = await stage.run_sql(
            message="run parallel query steps",
            route="deep_path",
            plan=plan,
        )
    finally:
        object.__setattr__(settings, "real_enable_parallel_sql", original_parallel_enabled)
        object.__setattr__(settings, "real_max_parallel_queries", original_parallel_limit)

    assert peak_active_calls > 1
    assert [row.rows[0]["segment"] for row in results] == ["step-a", "step-b", "step-c"]
    assert assumptions == [
        "assumption for step-a",
        "assumption for step-b",
        "assumption for step-c",
    ]
