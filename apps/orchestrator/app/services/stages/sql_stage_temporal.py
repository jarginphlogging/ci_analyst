from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app.models import SqlExecutionResult, TemporalScope


class TemporalScopeMismatchError(RuntimeError):
    pass


_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if _ISO_DATE_PATTERN.match(raw):
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return None
    if len(raw) >= 10 and _ISO_DATE_PATTERN.match(raw[:10]):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def period_start(value: date, unit: str) -> date:
    if unit == "day":
        return value
    if unit == "week":
        return value - timedelta(days=value.weekday())
    if unit == "month":
        return value.replace(day=1)
    if unit == "quarter":
        month = ((value.month - 1) // 3) * 3 + 1
        return value.replace(month=month, day=1)
    if unit == "year":
        return value.replace(month=1, day=1)
    return value


def add_period(start: date, unit: str) -> date:
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(weeks=1)
    if unit == "month":
        year = start.year + (start.month // 12)
        month = (start.month % 12) + 1
        return date(year, month, 1)
    if unit == "quarter":
        month_index = (start.month - 1) + 3
        year = start.year + (month_index // 12)
        month = (month_index % 12) + 1
        return date(year, month, 1)
    if unit == "year":
        return date(start.year + 1, 1, 1)
    return start


def best_date_column(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    best_column: str | None = None
    best_count = 0
    for column in rows[0].keys():
        count = 0
        for row in rows:
            if parse_date(row.get(column)) is not None:
                count += 1
        if count > best_count:
            best_count = count
            best_column = str(column)
    return best_column if best_count > 0 else None


def validate_temporal_scope_result(result: SqlExecutionResult, temporal_scope: TemporalScope) -> str | None:
    if temporal_scope.granularity is None:
        return None
    date_column = best_date_column(result.rows)
    if date_column is None:
        return None

    period_starts: set[date] = set()
    for row in result.rows:
        parsed = parse_date(row.get(date_column))
        if parsed is None:
            continue
        period_starts.add(period_start(parsed, temporal_scope.granularity))
    if not period_starts:
        return None

    ordered = sorted(period_starts)
    expected_count = temporal_scope.count
    if len(ordered) != expected_count:
        return (
            f"Temporal scope mismatch: expected {expected_count} {temporal_scope.granularity} period(s), "
            f"but found {len(ordered)} distinct period(s) in column '{date_column}'."
        )

    for index in range(1, len(ordered)):
        if ordered[index] != add_period(ordered[index - 1], temporal_scope.granularity):
            return (
                f"Temporal scope mismatch: expected contiguous {temporal_scope.granularity} periods "
                f"but found gaps in column '{date_column}'."
            )
    return None
