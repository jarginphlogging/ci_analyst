from __future__ import annotations

import pytest

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
async def test_planner_raises_when_llm_unavailable() -> None:
    async def failing_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("llm unavailable")

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=failing_ask_llm_json)
    with pytest.raises(RuntimeError, match="llm unavailable"):
        await stage.create_plan("Show me spend by state.", [])


@pytest.mark.asyncio
async def test_planner_preserves_single_task_from_planner() -> None:
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
    assert "cia_sales_insights_cortex" in decision.steps[0].goal


@pytest.mark.asyncio
async def test_planner_preserves_task_text_for_multi_step_plan() -> None:
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
    assert "cia_sales_insights_cortex" in decision.steps[0].goal
    assert "repeat_spend" in decision.steps[0].goal
    assert "new_spend" in decision.steps[0].goal


@pytest.mark.asyncio
async def test_planner_prompt_includes_general_step_minimization_policy() -> None:
    captured_system_prompt = ""

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal captured_system_prompt
        captured_system_prompt = str(kwargs.get("system_prompt", ""))
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
    assert "Output exactly one task when the question targets a single result set" in captured_system_prompt
    assert "Split when any of these apply" in captured_system_prompt
    assert "Incompatible time windows" in captured_system_prompt
    assert '"this year vs same period last year"' in captured_system_prompt


@pytest.mark.asyncio
async def test_planner_normalizes_stacked_area_chart_type_alias() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope trend composition request.",
            "presentationIntent": {"displayType": "chart", "chartType": "stacked-area"},
            "tooComplex": False,
            "tasks": [
                {
                    "task": "Show monthly sales split by customer type for the last 12 months.",
                    "dependsOn": [],
                    "independent": True,
                }
            ],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("Show monthly sales split by customer type for the last 12 months.", [])

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.displayType == "chart"
    assert decision.presentation_intent.chartType == "stacked_area"
    assert len(decision.steps) == 1


@pytest.mark.asyncio
async def test_planner_normalizes_depends_on_to_prior_step_ids() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope comparison request.",
            "presentationIntent": {"displayType": "table", "tableStyle": "comparison"},
            "tooComplex": False,
            "tasks": [
                {"task": "Identify top and bottom performing stores", "dependsOn": [], "independent": True},
                {
                    "task": "Show new vs repeat customer mix for those stores",
                    "dependsOn": ["Identify top and bottom performing stores"],
                    "independent": False,
                },
                {
                    "task": "Compare the same mix to last year",
                    "dependsOn": ["step_1", "Show new vs repeat customer mix for those stores", "task 2"],
                    "independent": False,
                },
            ],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan(
        "top and bottom stores with new vs repeat mix compared to last year",
        [],
    )

    assert decision.stop_reason == "none"
    assert [step.id for step in decision.steps] == ["step_1", "step_2", "step_3"]
    assert decision.steps[0].dependsOn == []
    assert decision.steps[1].dependsOn == ["step_1"]
    assert decision.steps[2].dependsOn == ["step_1", "step_2"]


@pytest.mark.asyncio
async def test_planner_infers_temporal_scope_for_last_n_months() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope trend request.",
            "presentationIntent": {"displayType": "chart", "chartType": "line"},
            "tooComplex": False,
            "tasks": [{"task": "Show new vs repeat customers by month for the last 6 months."}],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("Show me new vs repeat customers by month for the last 6 months.", [])

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.chartType == "stacked_area"
    assert decision.temporal_scope is not None
    assert decision.temporal_scope.unit == "month"
    assert decision.temporal_scope.count == 6
    assert decision.temporal_scope.granularity == "month"


@pytest.mark.asyncio
async def test_planner_keeps_line_for_non_composition_time_series() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope trend request.",
            "presentationIntent": {"displayType": "chart", "chartType": "line"},
            "tooComplex": False,
            "tasks": [{"task": "Show total sales by month for the last 6 months."}],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan("Show total sales by month for the last 6 months.", [])

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.chartType == "line"


@pytest.mark.asyncio
async def test_planner_preserves_structured_ranking_objectives() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "relevance": "in_domain",
            "relevanceReason": "In scope ranking request.",
            "presentationIntent": {
                "displayType": "table",
                "tableStyle": "ranked",
                "rationale": "User asked for highest values across two metrics.",
                "rankingObjectives": ["average ticket", "transaction volume"],
            },
            "tooComplex": False,
            "tasks": [{"task": "Rank day-of-week and time-window combinations by requested metrics."}],
        }

    stage = PlannerStage(model=load_semantic_model(), ask_llm_json=fake_ask_llm_json)
    decision = await stage.create_plan(
        "For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?",
        [],
    )

    assert decision.stop_reason == "none"
    assert decision.presentation_intent.tableStyle == "ranked"
    assert decision.presentation_intent.rankingObjectives == ["average ticket", "transaction volume"]
