from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from statistics import mean
from typing import Any, Optional, Union

from app.models import AnalysisArtifact, DataTable, EvidenceRow, MetricPoint, SqlExecutionResult

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

    # If the user did not ask for a breakdown dimension, prefer compact summary tables.
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
        if time_ratio >= 0.6 or any(token in name_lower for token in ["date", "month", "week", "quarter", "year"]):
            time_columns.append(column)
            continue

        if numeric_ratio >= 0.7:
            metric_columns.append(column)
            continue

        if text_ratio >= 0.6:
            dimension_columns.append(column)

    # Fall back to mixed-type columns if no dimensions were detected.
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
    query = message.lower()
    if any(token in query for token in ["store", "stores", "branch", "branches", "td_id", "location"]):
        return "store"
    if any(token in query for token in ["channel", "card present", "card not present", "cnp", "cp"]):
        return "channel"
    if any(token in query for token in ["state", "states"]):
        return "state"
    if any(token in query for token in ["trend", "month", "monthly", "week", "weekly", "quarter", "year", "yoy", "mom"]):
        return "time"
    return None


def _detect_result_grain(columns: list[str]) -> Optional[str]:
    lowered = [column.lower() for column in columns]
    if any(re.search(r"(td_id|store|branch|location|merchant)", column) for column in lowered):
        return "store"
    if any(re.search(r"(transaction_state|_state$|^state$)", column) for column in lowered):
        return "state"
    if any(re.search(r"(channel|card_present|card_not_present)", column) for column in lowered):
        return "channel"
    if any(re.search(r"(resp_date|date|month|week|quarter|year)", column) for column in lowered):
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


def _ranking_artifact(
    rows: list[dict[str, JsonValue]],
    *,
    dimension_column: str,
    value_column: str,
    max_rows: int,
) -> AnalysisArtifact:
    ranked: list[tuple[str, float]] = []
    for row in rows:
        dimension_value = row.get(dimension_column)
        value = _to_float(row.get(value_column))
        if value is None:
            continue
        label = str(dimension_value).strip() if dimension_value is not None else ""
        if not label:
            continue
        ranked.append((label, value))

    ranked.sort(key=lambda item: item[1], reverse=True)
    total = sum(value for _, value in ranked)
    cumulative = 0.0
    artifact_rows: list[dict[str, JsonValue]] = []
    for index, (label, value) in enumerate(ranked[:max_rows], start=1):
        cumulative += value
        share_pct = (value / total * 100.0) if total > 0 else 0.0
        cumulative_share_pct = (cumulative / total * 100.0) if total > 0 else 0.0
        artifact_rows.append(
            {
                "rank": index,
                dimension_column: label,
                value_column: float(value),
                "share_pct": round(share_pct, 2),
                "cumulative_share_pct": round(cumulative_share_pct, 2),
            }
        )

    title = f"{_column_label(dimension_column)} Ranking by {_column_label(value_column)}"
    description = (
        "Ranked distribution computed from retrieved SQL output. "
        f"Shows share and cumulative share across {len(ranked)} entities."
    )
    return AnalysisArtifact(
        id="artifact_ranking_1",
        kind="ranking_breakdown",
        title=title,
        description=description,
        columns=["rank", dimension_column, value_column, "share_pct", "cumulative_share_pct"],
        rows=artifact_rows,
        dimensionKey=dimension_column,
        valueKey=value_column,
    )


def _trend_artifact(
    rows: list[dict[str, JsonValue]],
    *,
    time_col: str,
    value_col: str,
    max_rows: int,
) -> AnalysisArtifact:
    ordered_rows = sorted(rows, key=lambda row: _time_sort_value(row.get(time_col)))
    trend_rows: list[dict[str, JsonValue]] = []
    previous: Optional[float] = None
    for row in ordered_rows[:max_rows]:
        value = _to_float(row.get(value_col))
        if value is None:
            continue
        change = (value - previous) if previous is not None else None
        trend_rows.append(
            {
                time_col: row.get(time_col),
                value_col: round(float(value), 4),
                "period_change": round(change, 4) if change is not None else None,
            }
        )
        previous = value

    return AnalysisArtifact(
        id="artifact_trend_1",
        kind="trend_breakdown",
        title=f"{_column_label(value_col)} Trend",
        description="Time-series trend derived from retrieved SQL output.",
        columns=[time_col, value_col, "period_change"],
        rows=trend_rows,
        timeKey=time_col,
        valueKey=value_col,
    )


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

    # Detect explicit year-over-year period pairs such as q4_2025 vs q4_2024.
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

    # Do not infer prior/current from unrelated metrics (e.g., sales vs transactions).
    if change_col is None and (current_col is None or prior_col is None):
        return dimension_col, None, None, None

    return dimension_col, prior_col, current_col, change_col


def _comparison_artifact(
    rows: list[dict[str, JsonValue]],
    *,
    dimension_col: str,
    prior_col: Optional[str],
    current_col: Optional[str],
    change_col: Optional[str],
    max_rows: int,
) -> AnalysisArtifact:
    artifact_rows: list[dict[str, JsonValue]] = []
    for row in rows[:max_rows]:
        prior_value = _to_float(row.get(prior_col)) if prior_col else None
        current_value = _to_float(row.get(current_col)) if current_col else None
        change_value = _to_float(row.get(change_col)) if change_col else None

        if change_value is None and prior_value is not None and current_value is not None:
            change_value = current_value - prior_value

        change_pct = None
        if prior_value not in {None, 0.0} and change_value is not None:
            change_pct = (change_value / prior_value) * 100.0

        artifact_rows.append(
            {
                dimension_col: row.get(dimension_col),
                "prior_value": prior_value,
                "current_value": current_value,
                "change_value": change_value,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
            }
        )

    return AnalysisArtifact(
        id="artifact_comparison_1",
        kind="comparison_breakdown",
        title=f"{_column_label(dimension_col)} Comparison",
        description="Current-versus-prior comparison generated from returned SQL rows.",
        columns=[dimension_col, "prior_value", "current_value", "change_value", "change_pct"],
        rows=artifact_rows,
        dimensionKey=dimension_col,
        valueKey="change_value",
    )


def _distribution_artifact(
    rows: list[dict[str, JsonValue]],
    *,
    metric_col: str,
    dimension_col: Optional[str],
) -> Optional[AnalysisArtifact]:
    values: list[tuple[Optional[str], float]] = []
    for row in rows:
        value = _to_float(row.get(metric_col))
        if value is None:
            continue
        label = str(row.get(dimension_col)) if dimension_col and row.get(dimension_col) is not None else None
        values.append((label, value))

    if len(values) < 3:
        return None

    ordered = sorted(values, key=lambda item: item[1])
    only_values = [item[1] for item in ordered]

    p10_index = max(0, min(len(only_values) - 1, int(round((len(only_values) - 1) * 0.10))))
    p50_index = max(0, min(len(only_values) - 1, int(round((len(only_values) - 1) * 0.50))))
    p90_index = max(0, min(len(only_values) - 1, int(round((len(only_values) - 1) * 0.90))))

    min_label, min_value = ordered[0]
    max_label, max_value = ordered[-1]

    summary_rows: list[dict[str, JsonValue]] = [
        {"stat": "count", "value": len(only_values), "label": None},
        {"stat": "mean", "value": round(mean(only_values), 4), "label": None},
        {"stat": "p10", "value": round(only_values[p10_index], 4), "label": None},
        {"stat": "median", "value": round(only_values[p50_index], 4), "label": None},
        {"stat": "p90", "value": round(only_values[p90_index], 4), "label": None},
        {"stat": "min", "value": round(min_value, 4), "label": min_label},
        {"stat": "max", "value": round(max_value, 4), "label": max_label},
    ]

    return AnalysisArtifact(
        id="artifact_distribution_1",
        kind="distribution_breakdown",
        title=f"{_column_label(metric_col)} Distribution",
        description="Distribution snapshot generated directly from retrieved rows.",
        columns=["stat", "value", "label"],
        rows=summary_rows,
        dimensionKey=dimension_col,
        valueKey=metric_col,
    )


def _artifact_score(kind: str, message: str) -> int:
    text = message.lower()
    if kind == "ranking_breakdown":
        score = 2
        if any(token in text for token in ["top", "bottom", "rank", "descending", "ascending", "highest", "lowest"]):
            score += 2
        return score
    if kind == "comparison_breakdown":
        score = 2
        if any(token in text for token in ["compare", "versus", "vs", "yoy", "mom", "change", "delta", "previous"]):
            score += 2
        return score
    if kind == "trend_breakdown":
        score = 2
        if any(token in text for token in ["trend", "month", "week", "quarter", "year", "over time"]):
            score += 2
        return score
    if kind == "distribution_breakdown":
        score = 1
        if any(token in text for token in ["distribution", "outlier", "spread", "variance", "volatility"]):
            score += 1
        return score
    return 0


def build_analysis_artifacts(
    results: list[SqlExecutionResult],
    message: str = "",
    max_rows: int = 30,
) -> list[AnalysisArtifact]:
    primary = _primary_result(results, message=message)
    if not primary or not primary.rows:
        return []

    rows = primary.rows
    profile = _profile_rows(rows)
    if not profile.columns:
        return []

    candidates: list[tuple[int, AnalysisArtifact]] = []

    if profile.dimension_columns and profile.metric_columns:
        dimension_col = _preferred_dimension(profile.dimension_columns, message)
        value_col = _preferred_metric(profile.metric_columns, message)
        if dimension_col and value_col:
            ranking = _ranking_artifact(rows, dimension_column=dimension_col, value_column=value_col, max_rows=max_rows)
            if ranking.rows:
                candidates.append((_artifact_score(ranking.kind, message), ranking))

    if profile.time_columns and profile.metric_columns:
        time_col = profile.time_columns[0]
        value_col = _preferred_metric(profile.metric_columns, message)
        if value_col:
            trend = _trend_artifact(rows, time_col=time_col, value_col=value_col, max_rows=max_rows)
            if trend.rows:
                candidates.append((_artifact_score(trend.kind, message), trend))

    dimension_col, prior_col, current_col, change_col = _comparison_columns(profile, message)
    if dimension_col and (change_col or (prior_col and current_col)):
        comparison = _comparison_artifact(
            rows,
            dimension_col=dimension_col,
            prior_col=prior_col,
            current_col=current_col,
            change_col=change_col,
            max_rows=max_rows,
        )
        if comparison.rows:
            candidates.append((_artifact_score(comparison.kind, message), comparison))

    metric_col = _preferred_metric(profile.metric_columns, message)
    if metric_col:
        distribution = _distribution_artifact(rows, metric_col=metric_col, dimension_col=_preferred_dimension(profile.dimension_columns, message))
        if distribution and distribution.rows:
            candidates.append((_artifact_score(distribution.kind, message), distribution))

    if not candidates:
        return []

    flags = _query_intent_flags(message)
    if flags["comparison"]:
        has_comparison = any(artifact.kind == "comparison_breakdown" for _, artifact in candidates)
        has_trend = any(artifact.kind == "trend_breakdown" for _, artifact in candidates)
        explicit_breakdown = flags["state"] or flags["store"] or flags["channel"] or flags["ranking"]
        if not has_comparison and not has_trend and not explicit_breakdown:
            # Do not show unrelated ranking/distribution modules for period-comparison prompts.
            return []
        if has_comparison:
            narrowed = [
                (score, artifact)
                for score, artifact in candidates
                if artifact.kind in {"comparison_breakdown", "trend_breakdown"}
            ]
            if narrowed:
                candidates = narrowed

    candidates.sort(key=lambda item: item[0], reverse=True)
    artifacts: list[AnalysisArtifact] = []
    seen_kinds: set[str] = set()
    for _, artifact in candidates:
        if artifact.kind in seen_kinds:
            continue
        seen_kinds.add(artifact.kind)
        artifacts.append(artifact)
        if len(artifacts) >= 3:
            break

    return artifacts


def build_evidence_rows(results: list[SqlExecutionResult], max_rows: int = 8, message: str = "") -> list[EvidenceRow]:
    primary = _primary_result(results, message=message)
    if not primary or not primary.rows:
        return []

    rows = primary.rows
    profile = _profile_rows(rows)
    dimension_col, prior_col, current_col, change_col = _comparison_columns(profile, "")

    if not dimension_col or not (change_col or (prior_col and current_col)):
        return []

    raw_evidence: list[tuple[str, float, float, float]] = []
    for index, row in enumerate(rows[:max_rows]):
        segment = str(row.get(dimension_col, f"Segment {index + 1}"))
        prior = _to_float(row.get(prior_col)) if prior_col else None
        current = _to_float(row.get(current_col)) if current_col else None
        change = _to_float(row.get(change_col)) if change_col else None

        prior_value = prior if prior is not None else 0.0
        current_value = current if current is not None else prior_value

        if change is None and prior is not None and current is not None:
            change = current - prior
        if change is None:
            change = 0.0

        raw_evidence.append((segment, prior_value, current_value, float(change)))

    total_abs_change = sum(abs(item[3]) for item in raw_evidence)
    contribution_default = 1.0 / max(1, len(raw_evidence))

    evidence: list[EvidenceRow] = []
    for segment, prior_value, current_value, change in raw_evidence:
        contribution = abs(change) / total_abs_change if total_abs_change > 0 else contribution_default
        evidence.append(
            EvidenceRow(
                segment=segment,
                prior=prior_value,
                current=current_value,
                changeBps=change,
                contribution=float(contribution),
            )
        )

    return evidence


def build_metric_points(results: list[SqlExecutionResult], evidence: list[EvidenceRow], message: str = "") -> list[MetricPoint]:
    total_rows = sum(result.rowCount for result in results)
    metrics: list[MetricPoint] = [MetricPoint(label="Rows Retrieved", value=float(total_rows), delta=0.0, unit="count")]

    primary = _primary_result(results, message=message)
    if primary and primary.rows:
        profile = _profile_rows(primary.rows)
        metric_col = _preferred_metric(profile.metric_columns, "")
        if metric_col:
            values = [_to_float(row.get(metric_col)) for row in primary.rows]
            numeric_values = [value for value in values if value is not None]
            if numeric_values:
                metrics.append(
                    MetricPoint(
                        label=f"Total {_column_label(metric_col)}",
                        value=float(sum(numeric_values)),
                        delta=0.0,
                        unit="count",
                    )
                )
                metrics.append(
                    MetricPoint(
                        label=f"Average {_column_label(metric_col)}",
                        value=float(mean(numeric_values)),
                        delta=0.0,
                        unit="count",
                    )
                )

    if len(metrics) < 3 and evidence:
        average_change = sum(row.changeBps for row in evidence) / len(evidence)
        metrics.append(MetricPoint(label="Average Segment Delta", value=average_change, delta=average_change, unit="bps"))

    while len(metrics) < 3:
        metrics.append(MetricPoint(label=f"Signal {len(metrics) + 1}", value=0.0, delta=0.0, unit="count"))

    return metrics[:3]


def summarize_results_for_prompt(results: list[SqlExecutionResult], max_rows: int = 5) -> str:
    if not results:
        return "No SQL results were returned."

    chunks: list[str] = []
    for index, result in enumerate(results, start=1):
        columns = list(result.rows[0].keys()) if result.rows else []
        column_text = ", ".join(columns) if columns else "none"
        sample = result.rows[:max_rows]
        chunks.append(
            f"Step {index}:\n"
            f"- SQL: {result.sql}\n"
            f"- Row count: {result.rowCount}\n"
            f"- Columns: {column_text}\n"
            f"- Sample rows: {sample}"
        )
    return "\n\n".join(chunks)
