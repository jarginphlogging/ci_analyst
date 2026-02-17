from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


_STATES: list[tuple[str, str]] = [
    ("CA", "Los Angeles"),
    ("TX", "Dallas"),
    ("FL", "Miami"),
    ("NY", "New York"),
    ("GA", "Atlanta"),
    ("IL", "Chicago"),
    ("PA", "Philadelphia"),
    ("OH", "Columbus"),
    ("NC", "Charlotte"),
    ("MI", "Detroit"),
    ("NJ", "Newark"),
    ("VA", "Richmond"),
    ("WA", "Seattle"),
    ("AZ", "Phoenix"),
    ("MA", "Boston"),
    ("TN", "Nashville"),
    ("IN", "Indianapolis"),
    ("MO", "Kansas City"),
    ("MD", "Baltimore"),
    ("WI", "Milwaukee"),
    ("CO", "Denver"),
    ("MN", "Minneapolis"),
    ("SC", "Charleston"),
    ("AL", "Birmingham"),
    ("LA", "New Orleans"),
    ("KY", "Louisville"),
    ("OR", "Portland"),
    ("OK", "Oklahoma City"),
    ("CT", "Hartford"),
    ("UT", "Salt Lake City"),
]

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MCCS = ["5411", "5812", "5311", "5732", "5999", "5541"]


def _month_points() -> list[date]:
    points: list[date] = []
    year = 2024
    month = 1
    for _ in range(24):
        points.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return points


def _build_sales_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for month_index, month_date in enumerate(_month_points()):
        resp_date = month_date.isoformat()
        for state_index, (state, city) in enumerate(_STATES):
            for channel in ("CP", "CNP"):
                base_transactions = 820 + (state_index * 23) + (month_index * 15) + (70 if channel == "CNP" else 0)
                avg_ticket = 30.5 + ((state_index % 6) * 0.9) + (month_index * 0.08) + (1.4 if channel == "CNP" else 0.8)
                total_spend = round(base_transactions * avg_ticket, 2)
                repeat_share = 0.56 + ((state_index % 5) * 0.012) - (0.03 if channel == "CNP" else 0.0)
                repeat_transactions = int(base_transactions * repeat_share)
                new_transactions = base_transactions - repeat_transactions
                repeat_spend = round(total_spend * (repeat_transactions / max(base_transactions, 1)), 2)
                new_spend = round(total_spend - repeat_spend, 2)

                for repeat_flag in ("Y", "N"):
                    row_transactions = repeat_transactions if repeat_flag == "Y" else new_transactions
                    row_spend = repeat_spend if repeat_flag == "Y" else new_spend
                    cp_transactions = row_transactions if channel == "CP" else 0
                    cnp_transactions = row_transactions if channel == "CNP" else 0
                    cp_spend = row_spend if channel == "CP" else 0.0
                    cnp_spend = row_spend if channel == "CNP" else 0.0

                    rows.append(
                        (
                            f"CO{(state_index % 4) + 1}",
                            f"TD{state_index + 1:03d}{(month_index % 8) + 1:02d}",
                            state,
                            city,
                            _MCCS[(state_index + month_index) % len(_MCCS)],
                            channel,
                            repeat_flag,
                            resp_date,
                            _DAYS[(state_index + month_index) % len(_DAYS)],
                            f"{8 + ((state_index + month_index) % 10):02d}:30:00",
                            "consumer" if (state_index % 3) else "commercial",
                            repeat_transactions if repeat_flag == "Y" else 0,
                            new_transactions if repeat_flag == "N" else 0,
                            repeat_spend if repeat_flag == "Y" else 0.0,
                            new_spend if repeat_flag == "N" else 0.0,
                            cp_transactions,
                            cnp_transactions,
                            cp_spend,
                            cnp_spend,
                            row_transactions,
                            row_spend,
                        )
                    )
    return rows


def _build_household_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for state_index, _ in enumerate(_STATES, start=1):
        rows.append(
            (
                f"TD{state_index:03d}01",
                "2024-01-01",
                "2025-12-31",
                5200 + state_index * 130,
            )
        )
    return rows


def ensure_sandbox_database(db_path: str, *, reset: bool = False) -> None:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if reset and path.exists():
        path.unlink()

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cia_sales_insights_cortex (
              co_id TEXT,
              td_id TEXT,
              transaction_state TEXT,
              transaction_city TEXT,
              mcc TEXT,
              channel TEXT,
              repeat_flag TEXT,
              resp_date TEXT,
              day_of_week TEXT,
              transaction_time TEXT,
              consumer_commercial TEXT,
              repeat_transactions INTEGER,
              new_transactions INTEGER,
              repeat_spend REAL,
              new_spend REAL,
              cp_transactions INTEGER,
              cnp_transactions INTEGER,
              cp_spend REAL,
              cnp_spend REAL,
              transactions INTEGER,
              spend REAL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cia_household_insights_cortex (
              td_id TEXT,
              date_from TEXT,
              date_through TEXT,
              households_count INTEGER
            )
            """
        )

        sales_count = cursor.execute("SELECT COUNT(*) FROM cia_sales_insights_cortex").fetchone()
        if not sales_count or int(sales_count[0]) == 0:
            cursor.executemany(
                """
                INSERT INTO cia_sales_insights_cortex (
                  co_id, td_id, transaction_state, transaction_city, mcc, channel, repeat_flag, resp_date,
                  day_of_week, transaction_time, consumer_commercial, repeat_transactions, new_transactions,
                  repeat_spend, new_spend, cp_transactions, cnp_transactions, cp_spend, cnp_spend,
                  transactions, spend
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _build_sales_rows(),
            )

        household_count = cursor.execute("SELECT COUNT(*) FROM cia_household_insights_cortex").fetchone()
        if not household_count or int(household_count[0]) == 0:
            cursor.executemany(
                """
                INSERT INTO cia_household_insights_cortex (td_id, date_from, date_through, households_count)
                VALUES (?, ?, ?, ?)
                """,
                _build_household_rows(),
            )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sales_state_date ON cia_sales_insights_cortex(transaction_state, resp_date)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_channel ON cia_sales_insights_cortex(channel)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_td_id ON cia_sales_insights_cortex(td_id)")
        conn.commit()


def rewrite_sql_for_sqlite(sql: str) -> str:
    rewritten = sql.strip().rstrip(";")
    rewritten = re.sub(r"\bDATE\s*'([^']+)'", r"'\1'", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\bILIKE\b", "LIKE", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"::\s*[a-zA-Z_][a-zA-Z0-9_]*", "", rewritten)
    rewritten = re.sub(r"\bTRUE\b", "1", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\bFALSE\b", "0", rewritten, flags=re.IGNORECASE)
    return rewritten


def execute_readonly_query(db_path: str, sql: str) -> list[dict[str, Any]]:
    rewritten = rewrite_sql_for_sqlite(sql)
    lowered = rewritten.lstrip().lower()
    if not lowered.startswith("select") and not lowered.startswith("with"):
        raise ValueError("Sandbox SQL must start with SELECT or WITH.")

    ensure_sandbox_database(db_path)
    with sqlite3.connect(Path(db_path).expanduser()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(rewritten)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]
