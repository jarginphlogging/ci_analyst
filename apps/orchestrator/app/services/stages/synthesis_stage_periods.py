from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from app.models import SqlExecutionResult, TemporalScope


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return None
    if len(raw) >= 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw[:10]):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _date_range_from_sql(sql: str) -> tuple[date, date] | None:
    between_match = re.search(r"between\s+'(\d{4}-\d{2}-\d{2})'\s+and\s+'(\d{4}-\d{2}-\d{2})'", sql, re.IGNORECASE)
    if between_match:
        start = _parse_iso_date(between_match.group(1))
        end = _parse_iso_date(between_match.group(2))
        if start and end:
            return (start, end) if start <= end else (end, start)

    year_match = re.search(r"year\s*\(\s*resp_date\s*\)\s*=\s*(20\d{2})", sql, re.IGNORECASE)
    if year_match:
        year = int(year_match.group(1))
        return date(year, 1, 1), date(year, 12, 31)
    return None


def _date_range_from_results(results: list[SqlExecutionResult]) -> tuple[date, date] | None:
    discovered: list[date] = []
    for result in results:
        for row in result.rows[:500]:
            for value in row.values():
                parsed = _parse_iso_date(value)
                if parsed is not None:
                    discovered.append(parsed)
    if not discovered:
        return None
    return min(discovered), max(discovered)


def _add_months(base: date, months: int) -> date:
    month_index = (base.month - 1) + months
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base.day, monthrange(year, month)[1])
    return date(year, month, day)


def _relative_date_range(scope: TemporalScope, *, anchor_end: date) -> tuple[date, date] | None:
    if scope.kind != "relative_last_n":
        return None
    count = max(1, int(scope.count))
    unit = scope.unit
    if unit == "day":
        start = anchor_end - timedelta(days=count - 1)
        return start, anchor_end
    if unit == "week":
        start = anchor_end - timedelta(days=(count * 7) - 1)
        return start, anchor_end
    if unit == "month":
        current_month_start = anchor_end.replace(day=1)
        start = _add_months(current_month_start, -(count - 1))
        return start, anchor_end
    if unit == "quarter":
        quarter_start_month = ((anchor_end.month - 1) // 3) * 3 + 1
        quarter_start = anchor_end.replace(month=quarter_start_month, day=1)
        start = _add_months(quarter_start, -((count - 1) * 3))
        return start, anchor_end
    if unit == "year":
        start = date(anchor_end.year - (count - 1), 1, 1)
        return start, anchor_end
    return None


def _year_from_message(message: str) -> tuple[date, date] | None:
    years = [int(match.group(1)) for match in re.finditer(r"\b(20\d{2})\b", message)]
    if len(years) != 1:
        return None
    year = years[0]
    return date(year, 1, 1), date(year, 12, 31)


def _derive_period_bounds(
    *,
    message: str,
    results: list[SqlExecutionResult],
    temporal_scope: TemporalScope | None,
) -> tuple[str, str, str] | None:
    from_results = _date_range_from_results(results)
    if from_results is not None:
        start, end = from_results
        return start.isoformat(), end.isoformat(), f"Period: {start.isoformat()} to {end.isoformat()}"

    sql_ranges: list[tuple[date, date]] = []
    for result in results:
        parsed = _date_range_from_sql(result.sql)
        if parsed is not None:
            sql_ranges.append(parsed)
    if sql_ranges:
        start = min(item[0] for item in sql_ranges)
        end = max(item[1] for item in sql_ranges)
        return start.isoformat(), end.isoformat(), f"Period: {start.isoformat()} to {end.isoformat()}"

    if temporal_scope is not None:
        anchor_end = datetime.now().date()
        derived = _relative_date_range(temporal_scope, anchor_end=anchor_end)
        if derived is not None:
            start, end = derived
            return start.isoformat(), end.isoformat(), f"Period: {start.isoformat()} to {end.isoformat()}"

    explicit_year = _year_from_message(message)
    if explicit_year is not None:
        start, end = explicit_year
        return start.isoformat(), end.isoformat(), f"Period: {start.isoformat()} to {end.isoformat()}"

    return None
