from __future__ import annotations

from app.models import SqlExecutionResult
from app.services.table_analysis import build_analysis_artifacts


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
            sql="SELECT metric, q4_2025, q4_2024, yoy_pct FROM some_cte ORDER BY q4_2025 DESC",
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


def test_build_analysis_artifacts_treats_day_of_week_as_dimension_not_time_axis() -> None:
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

    artifacts = build_analysis_artifacts(
        results,
        message="For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?",
    )

    assert artifacts
    assert all(artifact.kind != "trend_breakdown" for artifact in artifacts)
