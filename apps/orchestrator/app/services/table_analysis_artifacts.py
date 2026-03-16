from __future__ import annotations

from statistics import mean
from typing import Optional

from app.models import AnalysisArtifact, SqlExecutionResult
from app.services.table_analysis_common import (
    JsonValue,
    _column_label,
    _comparison_columns,
    _preferred_dimension,
    _preferred_metric,
    _profile_rows,
    _primary_result,
    _query_intent_flags,
    _time_sort_value,
    _to_float,
)


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
