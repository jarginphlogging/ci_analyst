from __future__ import annotations

import pytest

from app.services.semantic_model import load_semantic_model
from app.services.stages.planner_stage import PlannerStage


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
