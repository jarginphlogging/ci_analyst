from __future__ import annotations

import re
import sqlite3
from calendar import monthrange
from datetime import date, timedelta
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
_SEED_VERSION = "2"
_SEED_DATE_FROM = date(2024, 1, 1)
_SEED_DATE_THROUGH = date(2025, 12, 31)


def _date_points() -> list[date]:
    points: list[date] = []
    cursor = _SEED_DATE_FROM
    while cursor <= _SEED_DATE_THROUGH:
        points.append(cursor)
        cursor += timedelta(days=1)
    return points


def _build_sales_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for date_index, resp_day in enumerate(_date_points()):
        resp_date = resp_day.isoformat()
        month_index = ((resp_day.year - _SEED_DATE_FROM.year) * 12) + (resp_day.month - 1)
        intra_month_factor = (resp_day.day - 1) % 7
        for state_index, (state, city) in enumerate(_STATES):
            for channel in ("CP", "CNP"):
                base_transactions = (
                    820 + (state_index * 23) + (month_index * 15) + (intra_month_factor * 3) + (70 if channel == "CNP" else 0)
                )
                avg_ticket = (
                    30.5 + ((state_index % 6) * 0.9) + (month_index * 0.08) + (intra_month_factor * 0.05) + (1.4 if channel == "CNP" else 0.8)
                )
                total_spend = round(base_transactions * avg_ticket, 2)
                repeat_share = 0.56 + ((state_index % 5) * 0.012) - (0.03 if channel == "CNP" else 0.0)
                repeat_transactions = int(base_transactions * repeat_share)
                new_transactions = base_transactions - repeat_transactions
                repeat_spend = round(total_spend * (repeat_transactions / max(base_transactions, 1)), 2)
                new_spend = round(total_spend - repeat_spend, 2)

                for repeat_flag in (1, 0):
                    row_transactions = repeat_transactions if repeat_flag == 1 else new_transactions
                    row_spend = repeat_spend if repeat_flag == 1 else new_spend
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
                            _DAYS[resp_day.weekday()],
                            f"{8 + ((state_index + date_index) % 10):02d}:30:00",
                            "Consumer" if (state_index % 3) else "Commercial",
                            repeat_transactions if repeat_flag == 1 else 0,
                            new_transactions if repeat_flag == 0 else 0,
                            repeat_spend if repeat_flag == 1 else 0.0,
                            new_spend if repeat_flag == 0 else 0.0,
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
        for td_suffix in range(1, 9):
            rows.append(
                (
                    f"TD{state_index:03d}{td_suffix:02d}",
                    _SEED_DATE_FROM.isoformat(),
                    _SEED_DATE_THROUGH.isoformat(),
                    5200 + state_index * 130 + td_suffix * 17,
                )
            )
    # Keep semantic-model sample value represented in the mock dataset.
    rows.append(
        (
            "6182655",
            _SEED_DATE_FROM.isoformat(),
            _SEED_DATE_THROUGH.isoformat(),
            6400,
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
              repeat_flag INTEGER,
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sandbox_seed_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )

        sales_count = cursor.execute("SELECT COUNT(*) FROM cia_sales_insights_cortex").fetchone()
        seed_version_row = cursor.execute(
            "SELECT value FROM sandbox_seed_metadata WHERE key = 'seed_version'"
        ).fetchone()
        seed_version = str(seed_version_row[0]) if seed_version_row else ""
        should_reseed = (not sales_count or int(sales_count[0]) == 0) or seed_version != _SEED_VERSION

        if should_reseed:
            cursor.execute("DELETE FROM cia_sales_insights_cortex")
            cursor.execute("DELETE FROM cia_household_insights_cortex")
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

            cursor.executemany(
                """
                INSERT INTO cia_household_insights_cortex (td_id, date_from, date_through, households_count)
                VALUES (?, ?, ?, ?)
                """,
                _build_household_rows(),
            )
            cursor.execute(
                """
                INSERT INTO sandbox_seed_metadata(key, value)
                VALUES('seed_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (_SEED_VERSION,),
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


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("Expected a date-like value.")
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return date.fromisoformat(text)


def _add_months(base: date, months: int) -> date:
    month_index = (base.month - 1) + months
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base.day, monthrange(year, month)[1])
    return date(year, month, day)


def _sqlite_dateadd(part: Any, amount: Any, value: Any) -> str:
    unit = str(part or "").strip().lower().strip("'\"")
    delta = int(amount)
    base = _as_date(value)

    if unit in {"month", "months", "mon"}:
        return _add_months(base, delta).isoformat()
    if unit in {"day", "days"}:
        return (base + timedelta(days=delta)).isoformat()
    if unit in {"year", "years"}:
        return _add_months(base, delta * 12).isoformat()
    raise ValueError(f"Unsupported DATEADD part: {part}")


def _sqlite_date_trunc(part: Any, value: Any) -> str:
    unit = str(part or "").strip().lower().strip("'\"")
    base = _as_date(value)

    if unit in {"month", "months", "mon"}:
        return base.replace(day=1).isoformat()
    if unit in {"year", "years"}:
        return base.replace(month=1, day=1).isoformat()
    if unit in {"day", "days"}:
        return base.isoformat()
    raise ValueError(f"Unsupported DATE_TRUNC part: {part}")


def _sqlite_last_day(value: Any) -> str:
    base = _as_date(value)
    return base.replace(day=monthrange(base.year, base.month)[1]).isoformat()


def execute_readonly_query(db_path: str, sql: str) -> list[dict[str, Any]]:
    rewritten = rewrite_sql_for_sqlite(sql)
    lowered = rewritten.lstrip().lower()
    if not lowered.startswith("select") and not lowered.startswith("with"):
        raise ValueError("Sandbox SQL must start with SELECT or WITH.")

    ensure_sandbox_database(db_path)
    with sqlite3.connect(Path(db_path).expanduser()) as conn:
        conn.create_function("DATEADD", 3, _sqlite_dateadd)
        conn.create_function("DATE_TRUNC", 2, _sqlite_date_trunc)
        conn.create_function("LAST_DAY", 1, _sqlite_last_day)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(rewritten)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]
