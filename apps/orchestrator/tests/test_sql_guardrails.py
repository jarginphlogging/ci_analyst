from __future__ import annotations

import pytest

from app.config import settings
from app.services.semantic_policy import load_semantic_policy
from app.services.sql_guardrails import guard_sql


def test_guard_sql_enforces_limit_and_allowlist() -> None:
    policy = load_semantic_policy()
    sql = "SELECT transaction_state, SUM(spend) FROM cia_sales_insights_cortex GROUP BY transaction_state"
    guarded = guard_sql(sql, policy)

    assert "LIMIT" in guarded.upper()
    assert "cia_sales_insights_cortex" in guarded


def test_guard_sql_rejects_non_allowlisted_table() -> None:
    policy = load_semantic_policy()
    with pytest.raises(ValueError):
        guard_sql("SELECT * FROM secret_schema.raw_customers", policy)


def test_guard_sql_allows_cte_references_when_base_table_is_allowlisted() -> None:
    policy = load_semantic_policy()
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
    guarded = guard_sql(sql, policy)
    assert "FROM cia_sales_insights_cortex" in guarded


def test_guard_sql_rewrites_qualified_allowlisted_table_names() -> None:
    policy = load_semantic_policy()
    sql = (
        "SELECT SUM(spend) AS total_sales "
        "FROM prodexp_107618_db.ts_customer_insights.cia_sales_insights_cortex"
    )

    guarded = guard_sql(sql, policy)
    assert "from cia_sales_insights_cortex" in guarded.lower()
    assert "prodexp_107618_db.ts_customer_insights" not in guarded.lower()


def test_guard_sql_does_not_rewrite_qualified_table_names_in_prod_mode() -> None:
    policy = load_semantic_policy()
    sql = (
        "SELECT SUM(spend) AS total_sales "
        "FROM prodexp_107618_db.ts_customer_insights.cia_sales_insights_cortex"
    )

    original_provider_mode_raw = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        with pytest.raises(ValueError):
            guard_sql(sql, policy)
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)


def test_guard_sql_rewrites_qualified_table_names_in_prod_sandbox_mode() -> None:
    policy = load_semantic_policy()
    sql = (
        "SELECT SUM(spend) AS total_sales "
        "FROM prodexp_107618_db.ts_customer_insights.cia_sales_insights_cortex"
    )

    original_provider_mode_raw = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod-sandbox")
        guarded = guard_sql(sql, policy)
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert "from cia_sales_insights_cortex" in guarded.lower()
    assert "prodexp_107618_db.ts_customer_insights" not in guarded.lower()
