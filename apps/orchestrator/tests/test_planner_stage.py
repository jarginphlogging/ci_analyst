from __future__ import annotations

import pytest

from app.config import settings
from app.services.semantic_model import load_semantic_model
from app.services.stages.planner_stage import (
    OUT_OF_DOMAIN_MESSAGE,
    TOO_COMPLEX_MESSAGE,
    PlannerStage,
)


@pytest.mark.asyncio
async def test_planner_marks_out_of_domain_request() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "relevance": "out_of_domain",
            "relevanceReason": "No semantic entities matched.",
            "presentationIntent": {"displayType": "table", "tableStyle": "simple"},
            "tooComplex": False,
            "tasks": [],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("What is the weather today?", [])

    assert decision.stop_reason == "out_of_domain"
    assert decision.stop_message == OUT_OF_DOMAIN_MESSAGE
    assert decision.presentation_intent.displayType == "table"
    assert decision.steps == []


@pytest.mark.asyncio
async def test_planner_marks_too_complex_request() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope but needs too many independent tasks.",
            "presentationIntent": {"displayType": "chart", "chartType": "line"},
            "tooComplex": True,
            "tasks": [],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("Break down every metric by every hierarchy for all periods.", [])

    assert decision.stop_reason == "too_complex"
    assert decision.stop_message == TOO_COMPLEX_MESSAGE
    assert decision.presentation_intent.displayType == "chart"
    assert decision.steps == []


@pytest.mark.asyncio
async def test_planner_accepts_unclear_relevance_and_outputs_tasks() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "relevance": "unclear",
            "relevanceReason": "Some intent is ambiguous.",
            "presentationIntent": {"displayType": "table", "tableStyle": "ranked"},
            "tooComplex": False,
            "tasks": [
                {"task": "Compute top and bottom stores for Q4 2025 with spend and transactions."},
                {"task": "Compute repeat versus new customer mix for those stores for Q4 2025."},
                {"task": "Compute Q4 2024 equivalents and return YoY deltas by store."},
            ],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan(
        "For Q4 2025 what were my top and bottom stores and compare repeat/new mix to last year?",
        [],
    )

    assert decision.stop_reason == "none"
    assert decision.relevance == "unclear"
    assert decision.presentation_intent.displayType == "table"
    assert decision.presentation_intent.tableStyle == "ranked"
    assert len(decision.steps) == 3


@pytest.mark.asyncio
async def test_planner_falls_back_when_llm_unavailable() -> None:
    async def failing_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("llm unavailable")

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=failing_ask_llm_json)
    if settings.provider_mode in {"sandbox", "prod"}:
        with pytest.raises(RuntimeError, match="llm unavailable"):
            await stage.create_plan("Show me spend by state.", [])
        return

    decision = await stage.create_plan("Show me spend by state.", [])
    assert decision.stop_reason == "none"
    assert decision.presentation_intent.displayType in {"table", "chart"}
    assert len(decision.steps) >= 1


@pytest.mark.asyncio
async def test_planner_fast_path_forces_single_direct_task() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "relevance": "in_domain",
            "relevanceReason": "Sales request is in scope.",
            "presentationIntent": {"displayType": "table", "tableStyle": "simple"},
            "tooComplex": False,
            "tasks": [
                {
                    "task": (
                        "Calculate total sales for last month from the cia_sales_insights_cortex table. "
                        "Aggregate repeat_spend, new_spend, cp_spend, and cnp_spend, then include a composition breakdown."
                    )
                }
            ],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("What were my total sales for last month?", [])

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.displayType == "table"
    assert len(decision.steps) == 1
    assert decision.steps[0].goal.startswith("Calculate total sales for last month")
    assert "cia_sales_insights_cortex" not in decision.steps[0].goal


@pytest.mark.asyncio
async def test_planner_deep_path_strips_physical_schema_terms() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "relevance": "in_domain",
            "relevanceReason": "Comparison request is in scope.",
            "presentationIntent": {"displayType": "chart", "chartType": "grouped_bar"},
            "tooComplex": False,
            "tasks": [
                {
                    "task": (
                        "Compute channel spend for last quarter from cia_sales_insights_cortex and include repeat_spend and new_spend."
                    )
                },
                {
                    "task": (
                        "Compute prior-quarter spend from cia_sales_insights_cortex using resp_date and provide period deltas."
                    )
                },
            ],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan(
        "Compare spend by channel for last quarter versus the prior quarter.",
        [],
    )

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.displayType == "chart"
    assert decision.presentation_intent.chartType == "grouped_bar"
    assert len(decision.steps) == 2
    for step in decision.steps:
        assert "cia_sales_insights_cortex" not in step.goal
        assert "repeat_spend" not in step.goal
        assert "new_spend" not in step.goal


@pytest.mark.asyncio
async def test_planner_prompt_includes_general_step_minimization_policy() -> None:
    captured_user_prompt = ""

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal captured_user_prompt
        captured_user_prompt = str(kwargs.get("user_prompt", ""))
        return {
            "relevance": "in_domain",
            "relevanceReason": "Request is in scope.",
            "presentationIntent": {"displayType": "table", "tableStyle": "ranked"},
            "tooComplex": False,
            "tasks": [{"task": "Return one ranked table for the requested scope."}],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("What are my top and bottom states by sales in 2025?", [])

    assert decision.stop_reason == "none"
    assert "Default to one task when requested outputs share the same business scope" in captured_user_prompt
    assert "Split into multiple tasks only when a single readable output would be materially worse or impossible" in captured_user_prompt
