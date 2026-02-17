from __future__ import annotations

from pathlib import Path

import pytest

from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite


def test_ensure_sandbox_database_and_query(tmp_path: Path) -> None:
    db_path = tmp_path / "sandbox.db"
    ensure_sandbox_database(str(db_path))

    rows = execute_readonly_query(
        str(db_path),
        (
            "SELECT transaction_state, SUM(spend) AS spend_total "
            "FROM cia_sales_insights_cortex GROUP BY transaction_state ORDER BY spend_total DESC LIMIT 5"
        ),
    )

    assert len(rows) == 5
    assert "transaction_state" in rows[0]
    assert "spend_total" in rows[0]


def test_rewrite_sql_for_sqlite_handles_common_snowflake_tokens() -> None:
    rewritten = rewrite_sql_for_sqlite("SELECT DATE '2025-01-01' AS d, TRUE AS t, FALSE AS f, col::NUMBER FROM x;")
    assert "DATE '" not in rewritten
    assert "::NUMBER" not in rewritten
    assert "1 AS t" in rewritten
    assert "0 AS f" in rewritten


def test_execute_readonly_query_rejects_mutation(tmp_path: Path) -> None:
    db_path = tmp_path / "sandbox.db"
    ensure_sandbox_database(str(db_path))

    with pytest.raises(ValueError):
        execute_readonly_query(str(db_path), "DELETE FROM cia_sales_insights_cortex")
