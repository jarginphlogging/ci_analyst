from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite


def _semantic_model_yaml_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "semantic_model.yaml"
        if candidate.exists():
            return candidate
    raise RuntimeError("Could not locate semantic_model.yaml from tests path.")


def _yaml_required_columns() -> dict[str, set[str]]:
    text = _semantic_model_yaml_path().read_text(encoding="utf-8")
    lines = text.splitlines()

    start = next((idx for idx, line in enumerate(lines) if line.strip() == "tables:"), None)
    end = next((idx for idx, line in enumerate(lines) if line.strip() == "verified_queries:"), None)
    if start is None or end is None or end <= start:
        raise RuntimeError("semantic_model.yaml missing expected tables/verified_queries sections.")

    required: dict[str, set[str]] = {}
    current_table: str | None = None
    in_column_block = False

    for line in lines[start + 1 : end]:
        table_match = re.match(r"^  - name:\s*([A-Za-z0-9_]+)\s*$", line)
        if table_match:
            current_table = table_match.group(1).lower()
            required.setdefault(current_table, set())
            in_column_block = False
            continue

        stripped = line.strip()
        if stripped in {"dimensions:", "measures:", "time_dimensions:"}:
            in_column_block = True
            continue

        if in_column_block and current_table:
            expr_match = re.match(r"^\s*expr:\s*([A-Za-z0-9_]+)\s*$", line)
            if expr_match:
                required[current_table].add(expr_match.group(1).lower())

    if not required:
        raise RuntimeError("No semantic-model tables were parsed from semantic_model.yaml.")
    return required


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


def test_execute_readonly_query_supports_common_snowflake_date_functions(tmp_path: Path) -> None:
    db_path = tmp_path / "sandbox.db"
    ensure_sandbox_database(str(db_path))

    rows = execute_readonly_query(
        str(db_path),
        """
        WITH max_date_cte AS (
          SELECT MAX(resp_date) AS max_date
          FROM cia_sales_insights_cortex
        ),
        last_month_bounds AS (
          SELECT
            DATE_TRUNC('MONTH', DATEADD('MONTH', -1, max_date)) AS last_month_start,
            LAST_DAY(DATEADD('MONTH', -1, max_date)) AS last_month_end
          FROM max_date_cte
        )
        SELECT
          SUM(spend) AS total_sales,
          MIN(resp_date) AS data_from,
          MAX(resp_date) AS data_through
        FROM cia_sales_insights_cortex
        CROSS JOIN last_month_bounds
        WHERE resp_date >= last_month_bounds.last_month_start
          AND resp_date <= last_month_bounds.last_month_end
        """,
    )

    assert len(rows) == 1
    assert rows[0]["total_sales"] is not None
    assert rows[0]["data_from"] == "2025-11-01"
    assert rows[0]["data_through"] == "2025-11-30"


def test_seeded_sqlite_schema_covers_semantic_model_yaml(tmp_path: Path) -> None:
    db_path = tmp_path / "sandbox.db"
    ensure_sandbox_database(str(db_path), reset=True)
    required_columns = _yaml_required_columns()

    with sqlite3.connect(db_path) as conn:
        for table_name, expected_columns in required_columns.items():
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            assert table_exists is not None, f"Missing table from semantic_model.yaml: {table_name}"

            pragma_rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            existing_columns = {str(row[1]).lower() for row in pragma_rows}
            missing_columns = expected_columns - existing_columns
            assert not missing_columns, (
                f"Missing columns in {table_name}: {sorted(missing_columns)} "
                f"(expected from semantic_model.yaml)"
            )


def test_seeded_values_match_semantic_model_conventions(tmp_path: Path) -> None:
    db_path = tmp_path / "sandbox.db"
    ensure_sandbox_database(str(db_path), reset=True)

    date_range = execute_readonly_query(
        str(db_path),
        "SELECT MIN(resp_date) AS min_dt, MAX(resp_date) AS max_dt FROM cia_sales_insights_cortex",
    )[0]
    assert date_range["min_dt"] == "2024-01-01"
    assert date_range["max_dt"] == "2025-12-31"

    repeat_values = execute_readonly_query(
        str(db_path),
        "SELECT DISTINCT repeat_flag FROM cia_sales_insights_cortex ORDER BY repeat_flag",
    )
    assert [row["repeat_flag"] for row in repeat_values] == [0, 1]

    customer_types = execute_readonly_query(
        str(db_path),
        "SELECT DISTINCT consumer_commercial FROM cia_sales_insights_cortex ORDER BY consumer_commercial",
    )
    assert [row["consumer_commercial"] for row in customer_types] == ["Commercial", "Consumer"]

    sample_td = execute_readonly_query(
        str(db_path),
        "SELECT COUNT(*) AS cnt FROM cia_household_insights_cortex WHERE td_id = '6182655'",
    )[0]
    assert sample_td["cnt"] == 1
