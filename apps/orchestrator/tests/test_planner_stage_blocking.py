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
