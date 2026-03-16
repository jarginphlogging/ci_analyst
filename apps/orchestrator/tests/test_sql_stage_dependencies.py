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
    match = re.search(r"Step id:\s*(step-[a-z0-9]+)", user_prompt, flags=re.IGNORECASE)
    step_id = match.group(1).lower() if match else "step-x"
    return {
        "sql": (
            f"SELECT '{step_id}' AS segment, 1.0 AS prior, 2.0 AS current, 10.0 AS changeBps, 0.5 AS contribution "
            "FROM cia_sales_insights_cortex LIMIT 1"
        ),
        "assumptions": [f"assumption for {step_id}"],
    }


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
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        await stage.run_sql(message="Top stores and then repeat/new mix", plan=plan, history=[])
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert execution_order[:2] == ["step-1", "step-2"]


@pytest.mark.asyncio
async def test_sql_stage_generates_and_executes_dependent_levels_in_order() -> None:
    model = load_semantic_model()
    events: list[str] = []

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        step_id = str(kwargs.get("step_id", "")).lower()
        events.append(f"generate:{step_id}")
        if step_id == "step-1":
            return {
                "type": "sql_ready",
                "sql": (
                    "SELECT td_id, transaction_state, SUM(spend) AS spend_2025 "
                    "FROM cia_sales_insights_cortex GROUP BY td_id, transaction_state LIMIT 2"
                ),
                "assumptions": [],
            }
        return {
            "type": "sql_ready",
            "sql": "SELECT td_id, SUM(repeat_spend) AS repeat_spend, SUM(new_spend) AS new_spend FROM cia_sales_insights_cortex GROUP BY td_id LIMIT 2",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        if "repeat_spend" in sql.lower():
            events.append("execute:step-2")
            return [{"td_id": "6182655", "repeat_spend": 10.0, "new_spend": 5.0}]
        events.append("execute:step-1")
        return [{"td_id": "6182655", "transaction_state": "TX", "spend_2025": 42.1}]

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [
        QueryPlanStep(id="step-1", goal="Identify top and bottom stores"),
        QueryPlanStep(id="step-2", goal="Show new vs repeat mix for those stores", dependsOn=["step-1"], independent=False),
    ]

    await stage.run_sql(
        message="top and bottom stores with new vs repeat mix",
        plan=plan,
        history=[],
        conversation_id="conv-dependent-order",
    )

    assert events == ["generate:step-1", "execute:step-1", "generate:step-2", "execute:step-2"]


@pytest.mark.asyncio
async def test_sql_stage_uses_dependency_context_to_retry_user_clarification() -> None:
    model = load_semantic_model()
    analyst_calls: list[dict[str, object]] = []
    step_two_attempts = 0

    async def fake_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        nonlocal step_two_attempts
        analyst_calls.append(dict(kwargs))
        step_id = str(kwargs.get("step_id", "")).lower()
        if step_id == "step-1":
            return {
                "type": "sql_ready",
                "sql": (
                    "SELECT td_id, transaction_state, SUM(spend) AS spend_2025 "
                    "FROM cia_sales_insights_cortex GROUP BY td_id, transaction_state LIMIT 2"
                ),
                "assumptions": [],
            }

        step_two_attempts += 1
        if step_two_attempts == 1:
            return {
                "type": "clarification",
                "clarificationQuestion": "Please provide store IDs and top/bottom N.",
                "clarificationKind": "user_input_required",
                "assumptions": [],
            }
        return {
            "type": "sql_ready",
            "sql": "SELECT td_id, SUM(repeat_spend) AS repeat_spend, SUM(new_spend) AS new_spend FROM cia_sales_insights_cortex GROUP BY td_id LIMIT 2",
            "assumptions": [],
        }

    async def fake_sql(sql: str) -> list[dict[str, object]]:
        if "repeat_spend" in sql.lower():
            return [{"td_id": "6182655", "repeat_spend": 24.0, "new_spend": 12.0}]
        return [
            {"td_id": "6182655", "transaction_state": "TX", "spend_2025": 42.1},
            {"td_id": "6185581", "transaction_state": "NV", "spend_2025": 5.7},
        ]

    stage = SqlExecutionStage(model=model, ask_llm_json=_fake_ask_llm_json, sql_fn=fake_sql, analyst_fn=fake_analyst)
    plan = [
        QueryPlanStep(id="step-1", goal="Identify top and bottom stores"),
        QueryPlanStep(id="step-2", goal="Show new vs repeat mix for those stores", dependsOn=["step-1"], independent=False),
    ]

    outcome = await stage.run_sql(
        message=(
            "What were my top and bottom performing stores for 2025, what was the new vs repeat customer mix "
            "for each one, and how does that compare to the prior period?"
        ),
        plan=plan,
        history=[],
        conversation_id="conv-dependency-context",
    )

    assert len(outcome.results) == 2
    assert step_two_attempts == 2
    step_two_calls = [item for item in analyst_calls if str(item.get("step_id", "")).lower() == "step-2"]
    assert len(step_two_calls) == 2
    second_step_two_call = step_two_calls[1]
    dependency_context = second_step_two_call.get("dependency_context")
    assert isinstance(dependency_context, list)
    assert dependency_context
    first_dep = dependency_context[0] if isinstance(dependency_context[0], dict) else {}
    sample_rows = first_dep.get("sampleRows")
    assert isinstance(sample_rows, list)
    assert any(isinstance(row, dict) and row.get("td_id") == "6182655" for row in sample_rows)
    retry_feedback = second_step_two_call.get("retry_feedback")
    assert isinstance(retry_feedback, list)
    assert retry_feedback


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
        QueryPlanStep(id="step-2", goal="Show new vs repeat mix for those stores", dependsOn=["Identify top and bottom stores"], independent=False),
        QueryPlanStep(id="step-3", goal="Compare the same mix to last year", dependsOn=["task 2"], independent=False),
    ]

    original_provider_mode_raw = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        await stage.run_sql(
            message="top and bottom stores with new vs repeat mix and last year comparison",
            plan=plan,
            history=[],
        )
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert execution_order[:3] == ["step-1", "step-2", "step-3"]
