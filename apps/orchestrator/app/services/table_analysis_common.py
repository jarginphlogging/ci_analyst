from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional, Union

from app.models import DataTable, SqlExecutionResult

JsonValue = Optional[Union[str, int, float, bool]]


def _json_safe_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, JsonValue]]:
    normalized: list[dict[str, JsonValue]] = []
    for row in rows:
        normalized.append({str(key): _json_safe_value(value) for key, value in row.items()})
    return normalized


def results_to_data_tables(results: list[SqlExecutionResult]) -> list[DataTable]:
    tables: list[DataTable] = []
    for index, result in enumerate(results, start=1):
        columns = list(result.rows[0].keys()) if result.rows else []
        tables.append(
            DataTable(
                id=f"sql_step_{index}",
                name=f"SQL Step {index} Output",
                columns=columns,
                rows=result.rows,
                rowCount=result.rowCount,
                sourceSql=result.sql,
            )
        )
    return tables


def _is_numeric(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _column_label(column_name: str) -> str:
    return column_name.replace("_", " ").strip().title()


def _metric_unit(column_name: str) -> Literal["currency", "number", "percent"]:
    name = column_name.lower()
    if any(token in name for token in ("sales", "revenue", "spend", "amount", "cost")):
        return "currency"
    if any(token in name for token in ("pct", "percent", "share", "rate")):
        return "percent"
    return "number"


def _normalized_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _periodized_metric_signature(column_name: str) -> tuple[str, str] | None:
    tokens = _normalized_tokens(column_name)
    if len(tokens) < 2:
        return None

    year_indexes = [
        index
        for index, token in enumerate(tokens)
        if re.fullmatch(r"(?:19|20)\d{2}", token) or re.fullmatch(r"y(?:19|20)\d{2}", token)
    ]
    if not year_indexes:
        return None

    quarter_indexes = [index for index, token in enumerate(tokens) if re.fullmatch(r"q[1-4]", token)]
    year_index = year_indexes[-1]
    year_token = tokens[year_index][-4:]
    quarter_index = next((index for index in quarter_indexes if abs(index - year_index) == 1), None)

    remove_indexes = {year_index}
    if quarter_index is not None:
        remove_indexes.add(quarter_index)
        period_token = f"{tokens[quarter_index]}_{year_token}"
    else:
        period_token = year_token

    metric_tokens = [token for index, token in enumerate(tokens) if index not in remove_indexes]
    if not metric_tokens:
        return None
    return "_".join(metric_tokens), period_token


def _period_token_sort_key(token: str) -> tuple[int, int, str]:
    lowered = token.lower().strip()
    quarter_match = re.fullmatch(r"q([1-4])_((?:19|20)\d{2})", lowered)
    if quarter_match:
        return (int(quarter_match.group(2)), int(quarter_match.group(1)), lowered)
    year_match = re.fullmatch(r"(?:19|20)\d{2}", lowered)
    if year_match:
        return (int(year_match.group(0)), 5, lowered)
    return (0, 0, lowered)


def _period_token_label(token: str) -> str:
    lowered = token.lower().strip()
    quarter_match = re.fullmatch(r"q([1-4])_((?:19|20)\d{2})", lowered)
    if quarter_match:
        return f"Q{quarter_match.group(1)} {quarter_match.group(2)}"
    year_match = re.fullmatch(r"(?:19|20)\d{2}", lowered)
    if year_match:
        return year_match.group(0)
    return token.replace("_", " ").strip() or token


def _find_column(columns: list[str], candidates: list[str]) -> Optional[str]:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        token = candidate.lower()
        for lower, original in lowered.items():
            if token in lower:
                return original
    return None


def _to_float(value: JsonValue) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _is_time_value(value: JsonValue) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return True
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _time_sort_value(value: JsonValue) -> tuple[int, float]:
    if isinstance(value, datetime):
        return (0, value.timestamp())
    if isinstance(value, date):
        return (0, datetime.combine(value, datetime.min.time()).timestamp())
    if isinstance(value, str):
        raw = value.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            try:
                dt = datetime.fromisoformat(raw)
                return (0, dt.timestamp())
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return (0, dt.timestamp())
        except ValueError:
            return (1, 0.0)
    return (1, 0.0)


@dataclass(frozen=True)
class ResultProfile:
    columns: list[str]
    row_count: int
    time_columns: list[str]
    dimension_columns: list[str]
    metric_columns: list[str]


def _query_intent_flags(message: str) -> dict[str, bool]:
    text = message.lower()
    return {
        "ranking": any(token in text for token in ["top", "bottom", "rank", "descending", "ascending", "highest", "lowest"]),
        "comparison": any(token in text for token in ["compare", "versus", "vs", "yoy", "mom", "prior", "previous", "same period"]),
        "trend": any(token in text for token in ["trend", "over time", "monthly", "weekly", "daily", "by month", "by week"]),
        "state": "state" in text,
        "channel": any(token in text for token in ["channel", "card present", "card not present", "cnp", "cp"]),
        "store": any(token in text for token in ["store", "stores", "td_id", "location", "branch"]),
    }


def _is_categorical_time_bucket_column(column_name: str) -> bool:
    lowered = column_name.lower()
    return any(
        token in lowered
        for token in (
            "day_of_week",
            "weekday",
            "dow",
            "time_window",
            "hour_bucket",
            "hour_of_day",
        )
    )


def _result_relevance_score(result: SqlExecutionResult, message: str) -> float:
    if not result.rows:
        return float("-inf")

    flags = _query_intent_flags(message)
    columns = [column.lower() for column in result.rows[0].keys()]
    row_count = result.rowCount
    score = min(float(row_count), 60.0) * 0.2

    has_state = any(re.search(r"(transaction_state|_state$|^state$)", column) for column in columns)
    has_channel = any(re.search(r"(channel|card_present|card_not_present)", column) for column in columns)
    has_store = any(re.search(r"(td_id|store|branch|location)", column) for column in columns)
    has_time = any(re.search(r"(resp_date|date|month|week|quarter|year)", column) for column in columns)
    has_compare = any(re.search(r"(prior|previous|prev|current|latest|change|delta|yoy|mom|2024|2025)", column) for column in columns)
    has_metric_label = any(re.search(r"(^metric$|_metric$)", column) for column in columns)

    if flags["comparison"]:
        if has_compare:
            score += 24.0
        if has_metric_label:
            score += 8.0
    if flags["trend"] and has_time:
        score += 18.0
    if flags["ranking"] and (has_state or has_channel or has_store):
        score += 8.0

    if flags["state"]:
        score += 12.0 if has_state else -6.0
    elif has_state:
        score -= 6.0

    if flags["channel"]:
        score += 12.0 if has_channel else -6.0
    elif has_channel:
        score -= 4.0

    if flags["store"]:
        score += 12.0 if has_store else -6.0
    elif has_store:
        score -= 6.0

    if not any([flags["state"], flags["channel"], flags["store"], flags["trend"]]) and row_count > 12:
        score -= 6.0

    return score


def _primary_result(results: list[SqlExecutionResult], message: str = "") -> Optional[SqlExecutionResult]:
    if not results:
        return None

    if not message.strip():
        best: Optional[SqlExecutionResult] = None
        best_score = -1.0
        for result in results:
            if not result.rows:
                continue
            column_count = len(result.rows[0])
            score = (result.rowCount * 4.0) + column_count
            if result.rowCount <= 1:
                score -= 4.0
            if score > best_score:
                best_score = score
                best = result
        return best or results[0]

    best = None
    best_score = float("-inf")
    for result in results:
        score = _result_relevance_score(result, message)
        if score > best_score:
            best_score = score
            best = result

    return best or results[0]


def _profile_rows(rows: list[dict[str, JsonValue]], scan_limit: int = 200) -> ResultProfile:
    if not rows:
        return ResultProfile(columns=[], row_count=0, time_columns=[], dimension_columns=[], metric_columns=[])

    columns = list(rows[0].keys())
    scan_rows = rows[:scan_limit]
    time_columns: list[str] = []
    metric_columns: list[str] = []
    dimension_columns: list[str] = []

    for column in columns:
        values = [row.get(column) for row in scan_rows]
        non_null = [value for value in values if value is not None]
        if not non_null:
            continue

        numeric_count = sum(1 for value in non_null if _to_float(value) is not None)
        text_count = sum(1 for value in non_null if isinstance(value, str) and value.strip())
        time_count = sum(1 for value in non_null if _is_time_value(value))

        ratio_denominator = max(1, len(non_null))
        numeric_ratio = numeric_count / ratio_denominator
        text_ratio = text_count / ratio_denominator
        time_ratio = time_count / ratio_denominator

        name_lower = column.lower()
        if _is_categorical_time_bucket_column(name_lower):
            pass
        elif time_ratio >= 0.6 or any(token in name_lower for token in ["date", "month", "week", "quarter", "year"]):
            time_columns.append(column)
            continue

        if numeric_ratio >= 0.7:
            metric_columns.append(column)
            continue

        if text_ratio >= 0.6:
            dimension_columns.append(column)

    if not dimension_columns:
        for column in columns:
            if column in time_columns or column in metric_columns:
                continue
            dimension_columns.append(column)
            break

    return ResultProfile(
        columns=columns,
        row_count=len(rows),
        time_columns=time_columns,
        dimension_columns=dimension_columns,
        metric_columns=metric_columns,
    )


def _preferred_metric(metric_columns: list[str], message: str) -> Optional[str]:
    if not metric_columns:
        return None

    message_lower = message.lower()
    priority: list[tuple[str, list[str]]] = [
        ("avg", ["avg", "average", "ticket"]),
        ("spend", ["sales", "spend", "revenue", "amount"]),
        ("transactions", ["transactions", "count", "volume"]),
        ("share", ["share", "pct", "percent", "mix"]),
    ]
    for _, keywords in priority:
        if any(keyword in message_lower for keyword in keywords):
            selected = _find_column(metric_columns, keywords)
            if selected:
                return selected

    selected = _find_column(metric_columns, ["spend", "sales", "amount", "transactions", "count", "total"])
    return selected or metric_columns[0]


def _preferred_dimension(dimension_columns: list[str], message: str) -> Optional[str]:
    if not dimension_columns:
        return None

    selected = _find_column(
        dimension_columns,
        ["state", "city", "td_id", "store", "location", "channel", "segment", "category"],
    )
    if selected:
        return selected

    message_lower = message.lower()
    for column in dimension_columns:
        lower = column.lower()
        if any(token in message_lower for token in lower.replace("_", " ").split(" ")):
            return column

    return dimension_columns[0]


def _infer_requested_grain(message: str) -> Optional[str]:
    _ = message
    return None


def _detect_result_grain(columns: list[str]) -> Optional[str]:
    lowered = [column.lower() for column in columns]
    if any(re.search(r"(td_id|store|branch|location|merchant)", column) for column in lowered):
        return "store"
    if any(re.search(r"(transaction_state|_state$|^state$)", column) for column in lowered):
        return "state"
    if any(re.search(r"(channel|card_present|card_not_present)", column) for column in lowered):
        return "channel"
    if any(re.search(r"(resp_date|date|month|week|quarter|year)", column) for column in lowered) and not any(
        _is_categorical_time_bucket_column(column) for column in lowered
    ):
        return "time"
    return None


def detect_grain_mismatch(
    results: list[SqlExecutionResult],
    message: str,
) -> Optional[tuple[str, str]]:
    primary = _primary_result(results, message=message)
    if not primary or not primary.rows:
        return None

    required_grain = _infer_requested_grain(message)
    detected_grain = _detect_result_grain(list(primary.rows[0].keys()))
    if required_grain and detected_grain and required_grain != detected_grain:
        return required_grain, detected_grain
    return None


def _comparison_columns(profile: ResultProfile, message: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    dimension_col = _preferred_dimension(profile.dimension_columns, message)
    if not dimension_col:
        return None, None, None, None

    metric_columns = profile.metric_columns
    if not metric_columns:
        return dimension_col, None, None, None

    current_col = _find_column(metric_columns, ["current", "latest", "this"])
    prior_col = _find_column(metric_columns, ["prior", "previous", "prev", "baseline", "last"])
    change_col = _find_column(metric_columns, ["change", "delta", "yoy", "mom", "diff", "variance"])

    year_columns: list[tuple[int, str]] = []
    for column in metric_columns:
        match = re.search(r"(20\d{2})", column)
        if match:
            year_columns.append((int(match.group(1)), column))
    year_columns.sort(key=lambda item: item[0], reverse=True)
    if (current_col is None or prior_col is None) and len(year_columns) >= 2:
        current_year, candidate_current = year_columns[0]
        for prior_year, candidate_prior in year_columns[1:]:
            if prior_year < current_year:
                current_col = current_col or candidate_current
                prior_col = prior_col or candidate_prior
                break

    if change_col is None and (current_col is None or prior_col is None):
        return dimension_col, None, None, None

    return dimension_col, prior_col, current_col, change_col
