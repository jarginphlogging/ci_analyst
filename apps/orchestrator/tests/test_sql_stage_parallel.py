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
            history=[],
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


@pytest.mark.asyncio
async def test_sql_stage_repairs_primary_result_grain_when_needed() -> None:
    model = load_semantic_model()

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {
            "sql": (
                "SELECT transaction_state, SUM(spend) AS total_spend "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        lowered = sql.lower()
        if "td_id" in lowered and "transaction_city" in lowered and "transaction_state" in lowered:
            return [
                {
                    "td_id": "6182655",
                    "transaction_city": "Houston",
                    "transaction_state": "TX",
                    "total_spend": 421000.0,
                    "data_from": "2025-01-01",
                    "data_through": "2025-12-31",
                }
            ]
        return [
            {"transaction_state": "TX", "total_spend": 421000.0},
            {"transaction_state": "FL", "total_spend": 389000.0},
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Rank store performance for 2025")]

    results, assumptions = await stage.run_sql(
        message="What are my top and bottom performing stores for 2025?",
        route="fast_path",
        plan=plan,
        history=[],
    )

    assert results
    assert "td_id" in results[0].rows[0]
    assert any("Auto-repaired SQL output" in item for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_repairs_period_comparison_shape_when_needed() -> None:
    model = load_semantic_model()

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {
            "sql": (
                "SELECT transaction_state, SUM(spend) AS spend_total, SUM(transactions) AS transaction_total "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        lowered = sql.lower()
        if "metric_pairs" in lowered and "current_value" in lowered and "prior_value" in lowered:
            return [
                {"metric": "sales", "current_value": None, "prior_value": 8361126.0, "change_value": None, "change_pct": None},
                {"metric": "transactions", "current_value": None, "prior_value": 240930.0, "change_value": None, "change_pct": None},
                {"metric": "avg_sale_amount", "current_value": None, "prior_value": 34.70, "change_value": None, "change_pct": None},
            ]
        return [
            {"transaction_state": "UT", "spend_total": 3014322.72, "transaction_total": 81336},
            {"transaction_state": "CT", "spend_total": 2901243.84, "transaction_total": 80232},
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="Q4 comparison")]

    results, assumptions = await stage.run_sql(
        message="What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
        route="deep_path",
        plan=plan,
        history=[],
    )

    assert results
    assert results[0].rows
    assert "metric" in results[0].rows[0]
    assert "current_value" in results[0].rows[0]
    assert "prior_value" in results[0].rows[0]
    assert any("period-over-period comparison contract" in item for item in assumptions)


@pytest.mark.asyncio
async def test_sql_stage_repairs_missing_period_context_when_needed() -> None:
    model = load_semantic_model()

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {
            "sql": (
                "SELECT transaction_state, SUM(spend) AS total_spend "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state"
            ),
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        lowered = sql.lower()
        if "min(resp_date) as data_from" in lowered and "max(resp_date) as data_through" in lowered:
            return [
                {
                    "transaction_state": "UT",
                    "total_spend": 3014322.72,
                    "data_from": "2025-01-01",
                    "data_through": "2025-12-31",
                },
                {
                    "transaction_state": "CT",
                    "total_spend": 2901243.84,
                    "data_from": "2025-01-01",
                    "data_through": "2025-12-31",
                },
            ]
        return [
            {"transaction_state": "UT", "total_spend": 3014322.72},
            {"transaction_state": "CT", "total_spend": 2901243.84},
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=fake_ask_llm_json, sql_fn=fake_sql)
    plan = [QueryPlanStep(id="step-1", goal="State sales ranking")]

    results, assumptions = await stage.run_sql(
        message="Show me my sales in each state in descending order.",
        route="fast_path",
        plan=plan,
        history=[],
    )

    assert results
    assert "data_from" in results[0].rows[0]
    assert "data_through" in results[0].rows[0]
    assert any("required period context" in item for item in assumptions)
