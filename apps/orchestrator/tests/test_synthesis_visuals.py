from __future__ import annotations

import pytest

from app.models import PresentationIntent, SqlExecutionResult
from app.services.stages.synthesis_stage import SynthesisStage


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
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.chartConfig is not None
    assert response.chartConfig.type == "stacked_area"
    assert response.primaryVisual is not None
    assert response.primaryVisual.visualType == "trend"


@pytest.mark.asyncio
async def test_synthesis_stage_sanitizes_multiway_comparison_table_config() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "answer": "Q4 performance improved across all tracked metrics.",
            "whyItMatters": "Three-way comparison identifies where the acceleration concentrated.",
            "confidence": "high",
            "confidenceReason": "All required columns are present.",
            "summaryCards": [{"label": "Rows", "value": "3"}],
            "chartConfig": None,
            "tableConfig": {
                "style": "comparison",
                "columns": [
                    {"key": "metric", "label": "Metric", "format": "string", "align": "left"},
                    {"key": "q4_2023", "label": "Q4 2023", "format": "number", "align": "right"},
                    {"key": "q4_2024", "label": "Q4 2024", "format": "number", "align": "right"},
                    {"key": "q4_2025", "label": "Q4 2025", "format": "number", "align": "right"},
                ],
                "comparisonMode": "baseline",
                "comparisonKeys": ["q4_2023", "q4_2024", "q4_2025"],
                "baselineKey": "q4_2023",
                "deltaPolicy": "both",
                "maxComparandsBeforeChartSwitch": 5,
            },
            "insights": [{"title": "Largest move", "detail": "Sales shows the biggest absolute lift.", "importance": "high"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT metric, q4_2023, q4_2024, q4_2025 FROM q4_rollup",
            rows=[
                {"metric": "sales", "q4_2023": 251.9, "q4_2024": 259.1, "q4_2025": 301.7},
                {"metric": "transactions", "q4_2023": 7427510, "q4_2024": 7428740, "q4_2025": 8428740},
                {"metric": "avg_sale_amount", "q4_2023": 34.84, "q4_2024": 35.8, "q4_2025": 35.8},
            ],
            rowCount=3,
        )
    ]

    response = await stage.build_response(
        message="Compare Q4 2023, 2024, and 2025 across key metrics.",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="comparison"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.tableConfig is not None
    assert response.tableConfig.style == "comparison"
    assert response.tableConfig.comparisonMode == "baseline"
    assert response.tableConfig.comparisonKeys == ["q4_2023", "q4_2024", "q4_2025"]
    assert response.tableConfig.baselineKey == "q4_2023"
    assert response.tableConfig.deltaPolicy == "both"
    assert response.tableConfig.maxComparandsBeforeChartSwitch == 5


@pytest.mark.asyncio
async def test_synthesis_stage_infers_comparison_keys_when_llm_config_is_invalid() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "answer": "Q4 performance improved across all tracked metrics.",
            "whyItMatters": "Three-way comparison identifies where the acceleration concentrated.",
            "confidence": "high",
            "chartConfig": None,
            "tableConfig": {
                "style": "comparison",
                "columns": [
                    {"key": "metric", "label": "Metric", "format": "string", "align": "left"},
                    {"key": "q4_2023", "label": "Q4 2023", "format": "number", "align": "right"},
                    {"key": "q4_2024", "label": "Q4 2024", "format": "number", "align": "right"},
                    {"key": "q4_2025", "label": "Q4 2025", "format": "number", "align": "right"},
                ],
                "comparisonMode": "baseline",
                "comparisonKeys": ["not_a_column"],
                "baselineKey": "not_a_column",
                "deltaPolicy": "both",
            },
            "insights": [{"title": "Largest move", "detail": "Sales shows the biggest absolute lift.", "importance": "high"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT metric, q4_2023, q4_2024, q4_2025 FROM q4_rollup",
            rows=[
                {"metric": "sales", "q4_2023": 251.9, "q4_2024": 259.1, "q4_2025": 301.7},
                {"metric": "transactions", "q4_2023": 7427510, "q4_2024": 7428740, "q4_2025": 8428740},
            ],
            rowCount=2,
        )
    ]

    response = await stage.build_response(
        message="Compare Q4 2023, 2024, and 2025 across key metrics.",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="comparison"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.tableConfig is not None
    assert response.tableConfig.style == "comparison"
    assert len(response.tableConfig.comparisonKeys) >= 2
    assert response.tableConfig.baselineKey in response.tableConfig.comparisonKeys


@pytest.mark.asyncio
async def test_synthesis_stage_rejects_mixed_metric_family_comparison_keys() -> None:
    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "answer": "Q4 performance improved.",
            "whyItMatters": "Comparison highlights movement.",
            "confidence": "high",
            "chartConfig": None,
            "tableConfig": {
                "style": "comparison",
                "columns": [
                    {"key": "sales_2024", "label": "Sales 2024", "format": "number", "align": "right"},
                    {"key": "sales_2025", "label": "Sales 2025", "format": "number", "align": "right"},
                    {"key": "transactions_2024", "label": "Transactions 2024", "format": "number", "align": "right"},
                    {"key": "transactions_2025", "label": "Transactions 2025", "format": "number", "align": "right"},
                ],
                "comparisonMode": "baseline",
                "comparisonKeys": ["sales_2024", "sales_2025", "transactions_2024", "transactions_2025"],
                "baselineKey": "sales_2024",
                "deltaPolicy": "both",
            },
            "insights": [{"title": "Largest move", "detail": "Sales and transactions are both up.", "importance": "high"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT sales_2024, sales_2025, transactions_2024, transactions_2025, "
                "avg_sale_amount_2024, avg_sale_amount_2025"
            ),
            rows=[
                {
                    "sales_2024": 259073236.5,
                    "sales_2025": 301732926.9,
                    "transactions_2024": 7435140,
                    "transactions_2025": 8428740,
                    "avg_sale_amount_2024": 34.84,
                    "avg_sale_amount_2025": 35.8,
                }
            ],
            rowCount=1,
        )
    ]

    response = await stage.build_response(
        message="What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="comparison"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.tableConfig is not None
    assert response.tableConfig.style != "comparison"
    assert response.tableConfig.comparisonKeys == []
