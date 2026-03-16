from __future__ import annotations

from app.models import SqlExecutionResult
from app.services.table_analysis import build_evidence_rows, detect_grain_mismatch


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
