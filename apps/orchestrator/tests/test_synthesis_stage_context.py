from __future__ import annotations

import json
import re

import pytest

from app.models import PresentationIntent, QueryPlanStep, SqlExecutionResult
from app.services.stages.synthesis_stage import SynthesisStage


def _extract_context_payload(prompt_text: str) -> dict[str, object]:
    prefix = "Synthesis context package:\n"
    start = prompt_text.index(prefix) + len(prefix)
    context_text = prompt_text[start:].strip()
    if context_text.startswith("{"):
        return json.loads(context_text)

    def _extract_json_block(title: str) -> object:
        pattern = rf"### {re.escape(title)} \(JSON\)\n```json\n(.*?)\n```"
        match = re.search(pattern, context_text, re.DOTALL)
        if not match:
            raise AssertionError(f"Missing JSON block: {title}")
        return json.loads(match.group(1))

    def _extract_scalar(key: str) -> str | None:
        match = re.search(rf"^{re.escape(key)}:\s*(.*)$", context_text, re.MULTILINE)
        if not match:
            return None
        return match.group(1).strip()

    headline_scalar = _extract_scalar("Headline")
    headline = ""
    if headline_scalar:
        try:
            headline = str(json.loads(headline_scalar))
        except json.JSONDecodeError:
            headline = headline_scalar

    context: dict[str, object] = {
        "plan": _extract_json_block("Plan"),
        "subtaskStatus": _extract_json_block("Subtask Status"),
        "availableVisualArtifacts": _extract_json_block("Available Visual Artifacts"),
        "requestedClaimModes": _extract_json_block("Requested Claim Modes"),
        "supportedClaims": _extract_json_block("Supported Claims"),
        "unsupportedClaims": _extract_json_block("Unsupported Claims"),
        "observations": _extract_json_block("Observations"),
        "series": _extract_json_block("Series"),
        "dataQuality": _extract_json_block("Data Quality"),
        "executedSteps": _extract_json_block("Executed Steps"),
        "facts": _extract_json_block("Facts"),
        "comparisons": _extract_json_block("Comparisons"),
        "headlineEvidenceRefs": _extract_json_block("Headline Evidence Refs"),
        "evidenceStatus": _extract_scalar("EvidenceStatus") or "",
        "headline": headline,
    }

    ranking_evidence = _extract_json_block("Ranking Evidence")
    if ranking_evidence is not None:
        context["rankingEvidence"] = ranking_evidence

    evidence_empty_reason = _extract_scalar("EvidenceEmptyReason")
    if evidence_empty_reason:
        context["evidenceEmptyReason"] = evidence_empty_reason
    return context


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
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.answer == "Synthesis answer"
    assert response.confidenceReason
    assert response.summaryCards
    assert response.chartConfig is not None
    assert response.evidenceStatus in {"sufficient", "limited", "insufficient"}
    assert response.comparisons
    assert response.headline
    prompt_text = captured_prompts["user"]
    assert re.search(r'"displayType"\s*:\s*"chart"', prompt_text)
    assert re.search(r'"chartType"\s*:\s*"grouped_bar"', prompt_text)
    assert "### Facts (JSON)" in prompt_text
    assert "Evidence summary:" not in prompt_text
    context = _extract_context_payload(prompt_text)
    assert "queryContext" not in context
    assert "portfolioSummary" not in context
    assert context["plan"] == [{"id": "step_1", "goal": "Compute spend and transaction trend by state for Q4 2025."}]
    executed_steps = context["executedSteps"]
    assert isinstance(executed_steps, list) and executed_steps
    step_1 = executed_steps[0]
    assert isinstance(step_1, dict)
    assert "planStep" not in step_1
    assert "executedSql" not in step_1
    table_summary = step_1["tableSummary"]
    assert isinstance(table_summary, dict)
    assert "numericStats" not in table_summary
    assert "columns" in table_summary
    assert "nullRatePct" in table_summary
    assert "evidenceStatus" in context
    assert "headline" in context
    assert "comparisons" in context
    assert "requestedClaimModes" in context
    assert "supportedClaims" in context
    assert "observations" in context
    assert "series" in context
    assert "dataQuality" in context
    assert "evidenceEmptyReason" not in context
    subtask_status = context["subtaskStatus"]
    assert isinstance(subtask_status, list) and subtask_status
    first_subtask = subtask_status[0]
    assert isinstance(first_subtask, dict)
    assert first_subtask["status"] == "sufficient"
    assert "reason" not in first_subtask
    supported_claims = context["supportedClaims"]
    assert isinstance(supported_claims, list)


@pytest.mark.asyncio
async def test_synthesis_stage_formats_comparison_period_labels_and_deltas() -> None:
    captured_prompts: dict[str, str] = {}

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        captured_prompts["user"] = str(kwargs.get("user_prompt", ""))
        return {
            "answer": "Q4 performance improved year over year.",
            "whyItMatters": "Growth is broad across core metrics.",
            "confidence": "high",
            "confidenceReason": "Both periods are complete and comparable.",
            "summaryCards": [{"label": "Sales", "value": "$301.7M"}],
            "chartConfig": None,
            "tableConfig": {
                "style": "comparison",
                "columns": [
                    {"key": "total_sales", "label": "Sales", "format": "currency", "align": "right"},
                    {"key": "total_transactions", "label": "Transactions", "format": "number", "align": "right"},
                ],
                "sortBy": "total_sales",
                "sortDir": "desc",
                "showRank": False,
            },
            "insights": [{"title": "Lift", "detail": "Sales and transactions are both up.", "importance": "high"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT SUM(spend) AS total_sales, SUM(transactions) AS total_transactions, MIN(resp_date) AS data_from, MAX(resp_date) AS data_through FROM t WHERE resp_date BETWEEN '2024-10-01' AND '2024-12-31'",
            rows=[
                {
                    "total_sales": 259073236.5,
                    "total_transactions": 7435140,
                    "data_from": "2024-10-01",
                    "data_through": "2024-12-31",
                }
            ],
            rowCount=1,
        ),
        SqlExecutionResult(
            sql="SELECT SUM(spend) AS total_sales, SUM(transactions) AS total_transactions, MIN(resp_date) AS data_from, MAX(resp_date) AS data_through FROM t WHERE resp_date BETWEEN '2025-10-01' AND '2025-12-31'",
            rows=[
                {
                    "total_sales": 301732926.9,
                    "total_transactions": 8428740,
                    "data_from": "2025-10-01",
                    "data_through": "2025-12-31",
                }
            ],
            rowCount=1,
        ),
    ]

    _ = await stage.build_response(
        message="What were my sales and transactions for Q4 2025 compared to last year?",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="comparison"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    context = _extract_context_payload(captured_prompts["user"])
    comparisons = context["comparisons"]
    assert isinstance(comparisons, list) and comparisons
    sales_cmp = next((item for item in comparisons if isinstance(item, dict) and item.get("metric") == "total_sales"), None)
    assert sales_cmp is not None
    assert sales_cmp["priorPeriodLabel"] == "Q4 2024"
    assert sales_cmp["currentPeriodLabel"] == "Q4 2025"
    assert sales_cmp["pctDelta"] == 16.47
    assert sales_cmp["absDelta"] == 42659690.4


@pytest.mark.asyncio
async def test_synthesis_stage_marks_trend_claim_supported_without_fact_or_comparison_rows() -> None:
    captured_prompts: dict[str, str] = {}

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        captured_prompts["user"] = str(kwargs.get("user_prompt", ""))
        return {
            "answer": "New and repeat customers are shown month by month.",
            "whyItMatters": "This provides a recent monthly baseline for customer mix.",
            "confidence": "high",
            "confidenceReason": "The monthly time series is directly available.",
            "summaryCards": [],
            "chartConfig": {
                "type": "stacked_area",
                "x": "month",
                "y": ["new_customers", "repeat_customers"],
                "series": None,
                "xLabel": "Month",
                "yLabel": "Customers",
                "yFormat": "number",
            },
            "tableConfig": None,
            "insights": [],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT month, new_customers, repeat_customers, total_transactions "
                "FROM t ORDER BY month"
            ),
            rows=[
                {"month": "2025-07-01", "new_customers": 1176843, "repeat_customers": 1551627, "total_transactions": 2728470},
                {"month": "2025-08-01", "new_customers": 1162219, "repeat_customers": 1532381, "total_transactions": 2694600},
                {"month": "2025-09-01", "new_customers": 1172162, "repeat_customers": 1545490, "total_transactions": 2717652},
                {"month": "2025-10-01", "new_customers": 1182201, "repeat_customers": 1558743, "total_transactions": 2740944},
                {"month": "2025-11-01", "new_customers": 1232906, "repeat_customers": 1625638, "total_transactions": 2858544},
                {"month": "2025-12-01", "new_customers": 1236953, "repeat_customers": 1631017, "total_transactions": 2867970},
            ],
            rowCount=6,
        )
    ]

    response = await stage.build_response(
        message="Show me new vs repeat customers by month for the last 6 months.",
        plan=[],
        presentation_intent=PresentationIntent(displayType="chart", chartType="stacked_area"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    assert response.evidenceStatus == "sufficient"
    assert response.evidenceEmptyReason == ""
    context = _extract_context_payload(captured_prompts["user"])
    assert context["requestedClaimModes"] == ["trend"]
    supported_claims = context["supportedClaims"]
    assert isinstance(supported_claims, list) and supported_claims
    trend_claim = next((item for item in supported_claims if isinstance(item, dict) and item.get("mode") == "trend"), None)
    assert trend_claim is not None
    series = context["series"]
    assert isinstance(series, list) and series
    series_entry = series[0]
    assert isinstance(series_entry, dict)
    assert series_entry["timeKey"] == "month"
    assert series_entry["metricKeys"][:2] == ["new_customers", "repeat_customers"]


@pytest.mark.asyncio
async def test_synthesis_stage_includes_ranking_evidence_in_context_payload() -> None:
    captured_prompts: dict[str, str] = {}

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        captured_prompts["user"] = str(kwargs.get("user_prompt", ""))
        return {
            "answer": "State ranking is available in descending order.",
            "whyItMatters": "Concentration can be reviewed from the ranked evidence.",
            "confidence": "high",
            "confidenceReason": "Ranking rows are complete for all returned states.",
            "summaryCards": [{"label": "States", "value": "8"}],
            "chartConfig": None,
            "tableConfig": {
                "style": "ranked",
                "columns": [
                    {"key": "transaction_state", "label": "State", "format": "string", "align": "left"},
                    {"key": "total_sales", "label": "Total Sales", "format": "currency", "align": "right"},
                ],
                "sortBy": "total_sales",
                "sortDir": "desc",
                "showRank": True,
            },
            "insights": [{"title": "Ranking ready", "detail": "Top and bottom rows are available.", "importance": "medium"}],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": [],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, total_sales FROM ranked_state_sales",
            rows=[
                {"transaction_state": "UT", "total_sales": 950.0},
                {"transaction_state": "CT", "total_sales": 900.0},
                {"transaction_state": "OK", "total_sales": 850.0},
                {"transaction_state": "OR", "total_sales": 800.0},
                {"transaction_state": "AL", "total_sales": 750.0},
                {"transaction_state": "TX", "total_sales": 700.0},
                {"transaction_state": "NY", "total_sales": 650.0},
                {"transaction_state": "CA", "total_sales": 600.0},
            ],
            rowCount=8,
        )
    ]

    _ = await stage.build_response(
        message="Show me sales by state in descending order.",
        plan=[],
        presentation_intent=PresentationIntent(displayType="table", tableStyle="ranked"),
        results=results,
        prior_interpretation_notes=[],
        prior_caveats=[],
        prior_assumptions=[],
        history=[],
    )

    context = _extract_context_payload(captured_prompts["user"])
    ranking_evidence = context.get("rankingEvidence")
    assert isinstance(ranking_evidence, dict)
    assert ranking_evidence["dimensionKey"] == "transaction_state"
    assert ranking_evidence["valueKey"] == "total_sales"
    assert ranking_evidence["sortDir"] == "desc"
    assert ranking_evidence["entityCount"] == 8
    assert ranking_evidence["topRows"][0]["rank"] == 1
    assert ranking_evidence["topRows"][0]["transaction_state"] == "UT"
    assert ranking_evidence["topRows"][1]["rank"] == 2
    assert ranking_evidence["topRows"][1]["transaction_state"] == "CT"
    assert ranking_evidence["bottomRows"][-1]["rank"] == 8
    assert ranking_evidence["bottomRows"][-1]["transaction_state"] == "CA"


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
