from __future__ import annotations

import pytest

from app.services.semantic_model import load_semantic_model
from app.services.stages.planner_stage import PlannerStage


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
