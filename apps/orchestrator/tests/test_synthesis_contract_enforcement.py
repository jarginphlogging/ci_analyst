from __future__ import annotations

import pytest

from app.models import PresentationIntent, SqlExecutionResult
from app.services.stages.synthesis_stage import SynthesisStage


@pytest.mark.asyncio
async def test_synthesis_sets_day_level_period_bounds_from_year_sql_filter() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {}

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, SUM(spend) AS total_sales FROM t WHERE YEAR(resp_date) = 2025 GROUP BY transaction_state",
            rows=[
                {"transaction_state": "TX", "total_sales": 120.0},
                {"transaction_state": "FL", "total_sales": 90.0},
            ],
            rowCount=2,
        )
    ]

    response = await stage.build_response(
        message="Show me sales by state for 2025.",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="simple"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.summary.periodStart == "2025-01-01"
    assert response.summary.periodEnd == "2025-12-31"
    assert response.summary.periodLabel == "Period: 2025-01-01 to 2025-12-31"


@pytest.mark.asyncio
async def test_synthesis_enforces_dual_ranks_for_multi_objective_ranked_intent() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {}

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT day_of_week, transaction_time_window, AVG(spend) AS avg_ticket, "
                "SUM(transactions) AS transaction_volume FROM t GROUP BY 1,2"
            ),
            rows=[
                {"day_of_week": "Friday", "transaction_time_window": "18:00-21:00", "avg_ticket": 68.9, "transaction_volume": 1200},
                {"day_of_week": "Saturday", "transaction_time_window": "12:00-15:00", "avg_ticket": 61.2, "transaction_volume": 2100},
                {"day_of_week": "Monday", "transaction_time_window": "08:00-11:00", "avg_ticket": 44.5, "transaction_volume": 2600},
            ],
            rowCount=3,
        )
    ]

    response = await stage.build_response(
        message="For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?",
        plan=[],
        presentation_intent=PresentationIntent(
            displayType="table",
            tableStyle="ranked",
            rankingObjectives=["average ticket", "transaction volume"],
        ),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.visualization.tableConfig is not None
    assert response.visualization.tableConfig.style == "simple"
    assert response.visualization.tableConfig.sortDir == "asc"
    assert response.visualization.tableConfig.sortBy == "rank_by_avg_ticket"

    primary = response.data.dataTables[0]
    assert "rank_by_avg_ticket" in primary.columns
    assert "rank_by_transaction_volume" in primary.columns
    assert primary.rows[0]["rank_by_avg_ticket"] == 1
    assert primary.rows[2]["rank_by_transaction_volume"] == 1


@pytest.mark.asyncio
async def test_synthesis_rewrites_contradictory_confidence_reason_for_dual_objective_ranking() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "answer": "Dual objective answer.",
            "whyItMatters": "Dual objective impact.",
            "confidence": "medium",
            "confidenceReason": "The ranking evidence covers only one objective (average ticket).",
            "summaryCards": [],
            "chartConfig": None,
            "tableConfig": None,
            "insights": [],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT day_of_week, transaction_time_window, AVG(spend) AS avg_ticket, "
                "SUM(transactions) AS transaction_volume FROM t GROUP BY 1,2"
            ),
            rows=[
                {"day_of_week": "Friday", "transaction_time_window": "15:30:00", "avg_ticket": 35.97, "transaction_volume": 73416},
                {"day_of_week": "Wednesday", "transaction_time_window": "15:30:00", "avg_ticket": 35.89, "transaction_volume": 83538},
                {"day_of_week": "Monday", "transaction_time_window": "10:30:00", "avg_ticket": 35.72, "transaction_volume": 73722},
            ],
            rowCount=3,
        )
    ]

    response = await stage.build_response(
        message="For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?",
        plan=[],
        presentation_intent=PresentationIntent(
            displayType="table",
            tableStyle="ranked",
            rankingObjectives=["average ticket", "transaction volume"],
        ),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.summary.confidenceReason
    assert "only one objective" not in response.summary.confidenceReason.lower()
    assert "dual-objective ranking" in response.summary.confidenceReason.lower()
