from __future__ import annotations

from app.models import SqlExecutionResult
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_fact_comparison_signals,
    detect_grain_mismatch,
)


def test_build_analysis_artifacts_creates_ranking_breakdown() -> None:
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT transaction_state, SUM(spend) AS total_sales "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state ORDER BY total_sales DESC"
            ),
            rows=[
                {"transaction_state": "UT", "total_sales": 3014322.72},
                {"transaction_state": "CT", "total_sales": 2901243.84},
                {"transaction_state": "OK", "total_sales": 2790152.16},
            ],
            rowCount=3,
        )
    ]

    artifacts = build_analysis_artifacts(results, message="Show me sales by state in descending order.")

    assert artifacts
    ranking = next((artifact for artifact in artifacts if artifact.kind == "ranking_breakdown"), None)
    assert ranking is not None
    assert ranking.dimensionKey == "transaction_state"
    assert ranking.valueKey == "total_sales"
    assert ranking.rows[0]["rank"] == 1
    assert ranking.rows[0]["transaction_state"] == "UT"


def test_build_analysis_artifacts_creates_comparison_breakdown() -> None:
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT metric, q4_2025, q4_2024, yoy_pct "
                "FROM some_cte ORDER BY q4_2025 DESC"
            ),
            rows=[
                {"metric": "spend", "q4_2025": 742.6, "q4_2024": 656.4, "yoy_pct": 13.1},
                {"metric": "transactions", "q4_2025": 21410, "q4_2024": 19880, "yoy_pct": 7.7},
            ],
            rowCount=2,
        )
    ]

    artifacts = build_analysis_artifacts(results, message="compare Q4 2025 versus prior year")

    comparison = next((artifact for artifact in artifacts if artifact.kind == "comparison_breakdown"), None)
    assert comparison is not None
    assert comparison.dimensionKey == "metric"
    assert "change_value" in comparison.columns
    assert all(artifact.kind in {"comparison_breakdown", "trend_breakdown"} for artifact in artifacts)


def test_build_evidence_rows_returns_empty_for_simple_ranking_output() -> None:
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, SUM(spend) AS total_sales FROM cia_sales_insights_cortex GROUP BY transaction_state",
            rows=[
                {"transaction_state": "UT", "total_sales": 3014322.72},
                {"transaction_state": "CT", "total_sales": 2901243.84},
            ],
            rowCount=2,
        )
    ]

    assert build_evidence_rows(results) == []


def test_detect_grain_mismatch_requires_explicit_requested_grain() -> None:
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, SUM(spend) AS spend_total FROM cia_sales_insights_cortex GROUP BY transaction_state",
            rows=[
                {"transaction_state": "UT", "spend_total": 3014322.72},
                {"transaction_state": "CT", "spend_total": 2901243.84},
            ],
            rowCount=2,
        )
    ]

    mismatch = detect_grain_mismatch(results, "What are my top and bottom performing stores for 2025?")

    assert mismatch is None


def test_build_analysis_artifacts_prefers_comparison_table_for_q4_yoy_prompt() -> None:
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, SUM(spend) AS total_spend, SUM(transactions) AS total_transactions FROM cia_sales_insights_cortex GROUP BY transaction_state",
            rows=[
                {"transaction_state": "UT", "total_spend": 3014322.72, "total_transactions": 81336},
                {"transaction_state": "CT", "total_spend": 2901243.84, "total_transactions": 80232},
            ],
            rowCount=26,
        ),
        SqlExecutionResult(
            sql="SELECT metric, q4_2024, q4_2023, yoy_pct FROM q4_comparison",
            rows=[
                {"metric": "sales", "q4_2024": 8.36, "q4_2023": 7.91, "yoy_pct": 5.7},
                {"metric": "transactions", "q4_2024": 240930, "q4_2023": 229110, "yoy_pct": 5.2},
                {"metric": "avg_sale_amount", "q4_2024": 34.70, "q4_2023": 34.53, "yoy_pct": 0.5},
            ],
            rowCount=3,
        ),
    ]

    artifacts = build_analysis_artifacts(
        results,
        message="What were my sales, transactions, and average sale amount for Q4 2024 compared to the same period last year?",
    )

    assert artifacts
    primary = artifacts[0]
    assert primary.kind == "comparison_breakdown"
    assert primary.dimensionKey == "metric"


def test_build_analysis_artifacts_does_not_fake_comparison_from_unrelated_metrics() -> None:
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT transaction_state, SUM(spend) AS total_sales, SUM(transactions) AS total_transactions "
                "FROM cia_sales_insights_cortex GROUP BY transaction_state ORDER BY total_sales DESC"
            ),
            rows=[
                {"transaction_state": "UT", "total_sales": 3014322.72, "total_transactions": 81336},
                {"transaction_state": "CT", "total_sales": 2901243.84, "total_transactions": 80232},
                {"transaction_state": "OK", "total_sales": 2790152.16, "total_transactions": 79128},
            ],
            rowCount=3,
        )
    ]

    artifacts = build_analysis_artifacts(
        results,
        message="What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
    )

    assert artifacts == []


def test_build_fact_comparison_signals_supports_cross_step_single_row_comparison() -> None:
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

    facts, comparisons = build_fact_comparison_signals(
        results,
        message="What were my sales and transactions for Q4 2025 compared to last year?",
    )

    assert facts
    assert comparisons
    sales_comparison = next((item for item in comparisons if item.metric == "total_sales"), None)
    assert sales_comparison is not None
    assert sales_comparison.currentValue > sales_comparison.priorValue
    assert sales_comparison.salienceDriver in {"intent", "magnitude", "reliability", "completeness", "period_compatibility"}
    assert sales_comparison.salienceRank is not None


def test_build_fact_comparison_signals_supports_single_row_paired_comparison_columns() -> None:
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT 'Q4 2025' AS period, 301732926.9 AS sales, 8428740 AS transactions, 35.8 AS avg_sale_amount, "
                "'Q4 2024' AS comparison_period, 259073236.5 AS comparison_sales, 7435140 AS comparison_transactions, "
                "34.84 AS comparison_avg_sale_amount"
            ),
            rows=[
                {
                    "period": "Q4 2025",
                    "sales": 301732926.9,
                    "transactions": 8428740,
                    "avg_sale_amount": 35.8,
                    "comparison_period": "Q4 2024",
                    "comparison_sales": 259073236.5,
                    "comparison_transactions": 7435140,
                    "comparison_avg_sale_amount": 34.84,
                }
            ],
            rowCount=1,
        )
    ]

    _facts, comparisons = build_fact_comparison_signals(
        results,
        message="What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
    )

    assert comparisons
    by_metric = {item.metric: item for item in comparisons}
    assert "sales" in by_metric
    assert "transactions" in by_metric
    assert "avg_sale_amount" in by_metric
    assert by_metric["sales"].priorPeriod == "Q4 2024"
    assert by_metric["sales"].currentPeriod == "Q4 2025"
