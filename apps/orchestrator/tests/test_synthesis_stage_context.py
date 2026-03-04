from __future__ import annotations

import re

import pytest

from app.models import PresentationIntent, QueryPlanStep, SqlExecutionResult
from app.services.stages.synthesis_stage import SynthesisStage


@pytest.mark.asyncio
async def test_synthesis_stage_uses_plan_sql_and_table_summary_context() -> None:
    captured_prompts: dict[str, str] = {}

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        captured_prompts["system"] = str(kwargs.get("system_prompt", ""))
        captured_prompts["user"] = str(kwargs.get("user_prompt", ""))
        return {
            "answer": "Synthesis answer",
            "whyItMatters": "Synthesis impact",
            "confidence": "high",
            "confidenceReason": "High confidence due to complete and consistent table outputs.",
            "summaryCards": [
                {"label": "Total Sales", "value": "$98.4M", "detail": "Full month aggregate"},
                {"label": "MoM Change", "value": "+4.2%"},
            ],
            "chartConfig": {
                "type": "grouped_bar",
                "x": "transaction_state",
                "y": ["prior_value", "current_value"],
                "series": None,
                "xLabel": "State",
                "yLabel": "Value",
                "yFormat": "number",
            },
            "insights": [
                {
                    "title": "Top movement",
                    "detail": "TX has the largest movement.",
                    "importance": "high",
                }
            ],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": ["A1"],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    plan = [
        QueryPlanStep(
            id="step_1",
            goal="Compute spend and transaction trend by state for Q4 2025.",
            dependsOn=[],
            independent=True,
        )
    ]
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT transaction_state, current_value, prior_value, change_value "
                "FROM cia_sales_insights_cortex"
            ),
            rows=[
                {
                    "transaction_state": "TX",
                    "current_value": 120.0,
                    "prior_value": 100.0,
                    "change_value": 20.0,
                },
                {
                    "transaction_state": "FL",
                    "current_value": 90.0,
                    "prior_value": 110.0,
                    "change_value": -20.0,
                },
            ],
            rowCount=2,
        )
    ]

    response = await stage.build_response(
        message="Compare Q4 2025 performance by state.",
        plan=plan,
        presentation_intent=PresentationIntent(displayType="chart", chartType="grouped_bar"),
        results=results,
        prior_assumptions=[],
        history=[],
    )

    assert response.answer == "Synthesis answer"
    assert response.confidenceReason
    assert response.summaryCards
    assert response.chartConfig is not None
    prompt_text = captured_prompts["user"]
    assert re.search(r'"originalUserQuery"\s*:\s*"Compare Q4 2025 performance by state\."', prompt_text)
    assert re.search(r'"displayType"\s*:\s*"chart"', prompt_text)
    assert re.search(r'"chartType"\s*:\s*"grouped_bar"', prompt_text)
    assert re.search(r'"plan"\s*:\s*\[\s*\{\s*"id"\s*:\s*"step_1"', prompt_text)
    assert re.search(
        r'"executedSql"\s*:\s*"SELECT transaction_state, current_value, prior_value, change_value FROM cia_sales_insights_cortex"',
        prompt_text,
    )
    assert '"availableVisualArtifacts"' in prompt_text
    assert '"tableSummary":' in prompt_text
    assert '"numericStats"' in prompt_text


@pytest.mark.asyncio
async def test_synthesis_stage_accepts_stacked_area_chart_config() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "answer": "Sales are rising and repeat customers now drive a larger share over time.",
            "whyItMatters": "Composition trend highlights retention momentum.",
            "confidence": "high",
            "confidenceReason": "Data is complete across the period.",
            "summaryCards": [{"label": "Latest Month", "value": "$12.3M"}],
            "chartConfig": {
                "type": "stacked_area",
                "x": "month",
                "y": "sales",
                "series": "customer_type",
                "xLabel": "Month",
                "yLabel": "Sales",
                "yFormat": "currency",
            },
            "tableConfig": None,
            "insights": [{"title": "Repeat share up", "detail": "Repeat segment contribution is increasing.", "importance": "high"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT month, customer_type, sales FROM cia_sales_insights_cortex",
            rows=[
                {"month": "2025-01-01", "customer_type": "new", "sales": 50.0},
                {"month": "2025-01-01", "customer_type": "repeat", "sales": 75.0},
                {"month": "2025-02-01", "customer_type": "new", "sales": 60.0},
                {"month": "2025-02-01", "customer_type": "repeat", "sales": 85.0},
                {"month": "2025-03-01", "customer_type": "new", "sales": 55.0},
                {"month": "2025-03-01", "customer_type": "repeat", "sales": 95.0},
            ],
            rowCount=6,
        )
    ]

    response = await stage.build_response(
        message="How is monthly sales composition changing between new and repeat customers?",
        plan=[],
        presentation_intent=PresentationIntent(displayType="chart", chartType="stacked_area"),
        results=results,
        prior_assumptions=[],
        history=[],
    )

    assert response.chartConfig is not None
    assert response.chartConfig.type == "stacked_area"
    assert response.primaryVisual is not None
    assert response.primaryVisual.visualType == "trend"
