from __future__ import annotations

import pytest

from app.services.semantic_model import load_semantic_model
from app.services.sql_guardrails import guard_sql


def test_guard_sql_enforces_limit_and_allowlist() -> None:
    model = load_semantic_model()
    sql = "SELECT transaction_state, SUM(spend) FROM cia_sales_insights_cortex GROUP BY transaction_state"
    guarded = guard_sql(sql, model)

    assert "LIMIT" in guarded.upper()
    assert "cia_sales_insights_cortex" in guarded


def test_guard_sql_rejects_non_allowlisted_table() -> None:
    model = load_semantic_model()
    with pytest.raises(ValueError):
        guard_sql("SELECT * FROM secret_schema.raw_customers", model)


def test_guard_sql_allows_cte_references_when_base_table_is_allowlisted() -> None:
    model = load_semantic_model()
    sql = """
WITH scoped AS (
  SELECT resp_date, spend
  FROM cia_sales_insights_cortex
),
agg AS (
  SELECT SUM(spend) AS total_spend
  FROM scoped
)
SELECT total_spend
FROM agg
"""
    guarded = guard_sql(sql, model)
    assert "FROM cia_sales_insights_cortex" in guarded
