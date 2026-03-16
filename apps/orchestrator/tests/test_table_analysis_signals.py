from __future__ import annotations

from app.models import SqlExecutionResult
from app.services.table_analysis import build_fact_comparison_signals


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


def test_build_fact_comparison_signals_supports_single_row_periodized_metric_columns() -> None:
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

    _facts, comparisons = build_fact_comparison_signals(
        results,
        message="What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
    )

    assert comparisons
    by_metric = {item.metric: item for item in comparisons}
    assert "sales" in by_metric
    assert "transactions" in by_metric
    assert "avg_sale_amount" in by_metric
    assert by_metric["sales"].priorPeriod == "2024"
    assert by_metric["sales"].currentPeriod == "2025"
