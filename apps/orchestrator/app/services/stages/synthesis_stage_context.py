from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from app.models import (
    AnalysisArtifact,
    ClaimSupport,
    ComparisonSignal,
    DataTable,
    EvidenceReference,
    EvidenceStatus,
    FactSignal,
    PresentationIntent,
    QueryPlanStep,
    SqlExecutionResult,
    SubtaskStatus,
    SynthesisContextPackage,
    SynthesisExecutedStep,
    SynthesisPlanStep,
    SynthesisPortfolioSummary,
    SynthesisQueryContext,
    SynthesisVisualArtifact,
)
from app.services.stages.synthesis_stage_common import _as_float, _column_kind
from app.services.stages.synthesis_stage_periods import _parse_iso_date

_PROMPT_SAMPLE_ROW_CAP = 3
_PROMPT_SAMPLE_COLUMN_CAP = 8
_CONTEXT_FACT_CAP = 20
_CONTEXT_COMPARISON_CAP = 14


def _requested_claim_modes(
    *,
    message: str,
    presentation_intent: PresentationIntent,
    step_count: int,
) -> list[str]:
    text = message.lower()
    requested: set[str] = set()

    if step_count > 1:
        requested.add("multi_step_synthesis")

    if presentation_intent.displayType == "chart":
        if presentation_intent.chartType in {"line", "stacked_area"}:
            requested.add("trend")
        elif presentation_intent.chartType == "stacked_bar":
            requested.add("composition")
        elif presentation_intent.chartType in {"bar", "grouped_bar"}:
            if any(token in text for token in ("top", "bottom", "rank", "highest", "lowest")):
                requested.add("ranking")
            elif any(token in text for token in ("compare", "versus", "yoy", "mom", "delta", "change")):
                requested.add("comparison")
            else:
                requested.add("snapshot")

    if presentation_intent.displayType == "table":
        if presentation_intent.tableStyle == "comparison":
            requested.add("comparison")
        elif presentation_intent.tableStyle == "ranked":
            requested.add("ranking")
        else:
            requested.add("snapshot")

    keyword_modes: dict[str, tuple[str, ...]] = {
        "trend": ("trend", "over time", "month", "months", "week", "weeks", "quarter", "quarters", "year", "years", "daily", "weekly", "monthly"),
        "comparison": ("compare", "versus", "yoy", "mom", "delta", "change", "prior", "previous"),
        "ranking": ("top", "bottom", "rank", "highest", "lowest", "best", "worst"),
        "composition": ("mix", "share", "split", "composition", "contribution", "breakdown"),
        "distribution": ("distribution", "spread", "variance", "volatility", "outlier", "percentile", "skew"),
    }
    for mode, tokens in keyword_modes.items():
        if any(token in text for token in tokens):
            requested.add(mode)

    if not requested:
        requested.add("snapshot")

    ordered_modes = (
        "snapshot",
        "trend",
        "comparison",
        "ranking",
        "composition",
        "distribution",
        "multi_step_synthesis",
    )
    return [mode for mode in ordered_modes if mode in requested]


def _infer_table_roles(table: DataTable) -> tuple[list[str], list[str], list[str]]:
    date_columns = [column for column in table.columns if _column_kind(table, column) == "date"]
    numeric_columns = [column for column in table.columns if _column_kind(table, column) == "number"]
    excluded = set(date_columns).union(numeric_columns)
    dimension_columns = [column for column in table.columns if column not in excluded]
    return date_columns, numeric_columns, dimension_columns


def _sort_rows_by_column(rows: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        value = row.get(column)
        if isinstance(value, str):
            parsed = _parse_iso_date(value)
            if parsed is not None:
                return (0, float(parsed.toordinal()), value)
            return (1, 0.0, value)
        if isinstance(value, (date, datetime)):
            normalized = value.date() if isinstance(value, datetime) else value
            return (0, float(normalized.toordinal()), normalized.isoformat())
        return (2, 0.0, str(value))

    return sorted(rows, key=_sort_key)


def _build_observations(data_tables: list[DataTable]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for step_index, table in enumerate(data_tables, start=1):
        if not table.rows:
            continue
        date_columns, numeric_columns, dimension_columns = _infer_table_roles(table)
        if table.rowCount == 1 and numeric_columns:
            row = table.rows[0]
            metrics = []
            for column in numeric_columns[:4]:
                value = _as_float(row.get(column))
                if value is None:
                    continue
                metrics.append({"metric": column, "value": value, "unit": "number"})
            if metrics:
                observations.append(
                    {
                        "stepIndex": step_index,
                        "type": "single_row_summary",
                        "period": str(row.get(date_columns[0])) if date_columns else None,
                        "metrics": metrics,
                    }
                )
            continue
        if date_columns or not numeric_columns or not dimension_columns:
            continue
        dimension_key = dimension_columns[0]
        metric_keys = numeric_columns[:2]
        row_observations: list[dict[str, Any]] = []
        for row in table.rows[:5]:
            metric_values = {
                metric: _as_float(row.get(metric))
                for metric in metric_keys
                if _as_float(row.get(metric)) is not None
            }
            if not metric_values:
                continue
            row_observations.append({"dimensionValue": row.get(dimension_key), "metrics": metric_values})
        if row_observations:
            observations.append(
                {
                    "stepIndex": step_index,
                    "type": "row_observations",
                    "dimensionKey": dimension_key,
                    "rows": row_observations,
                }
            )
    return observations[:8]


def _build_series(data_tables: list[DataTable]) -> list[dict[str, Any]]:
    series_entries: list[dict[str, Any]] = []
    for step_index, table in enumerate(data_tables, start=1):
        if table.rowCount < 2 or not table.rows:
            continue
        date_columns, numeric_columns, _dimension_columns = _infer_table_roles(table)
        if not date_columns or not numeric_columns:
            continue
        time_key = date_columns[0]
        metric_keys = numeric_columns[:3]
        ordered_rows = _sort_rows_by_column(table.rows, time_key)
        trimmed_rows = ordered_rows[:12]
        points: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for row in trimmed_rows:
            point: dict[str, Any] = {time_key: row.get(time_key)}
            for metric_key in metric_keys:
                point[metric_key] = _as_float(row.get(metric_key))
            points.append(point)

        for metric_key in metric_keys:
            metric_points = [
                (row.get(time_key), _as_float(row.get(metric_key)))
                for row in ordered_rows
                if _as_float(row.get(metric_key)) is not None
            ]
            if len(metric_points) < 2:
                continue
            start_period, start_value = metric_points[0]
            end_period, end_value = metric_points[-1]
            max_period, max_value = max(metric_points, key=lambda item: item[1] or float("-inf"))
            min_period, min_value = min(metric_points, key=lambda item: item[1] or float("inf"))
            abs_delta = (end_value or 0.0) - (start_value or 0.0)
            pct_delta = None if start_value in {None, 0.0} else (abs_delta / start_value) * 100.0
            summaries.append(
                {
                    "metric": metric_key,
                    "startPeriod": start_period,
                    "startValue": start_value,
                    "endPeriod": end_period,
                    "endValue": end_value,
                    "absDelta": abs_delta,
                    "pctDelta": round(pct_delta, 2) if pct_delta is not None else None,
                    "peakPeriod": max_period,
                    "peakValue": max_value,
                    "troughPeriod": min_period,
                    "troughValue": min_value,
                }
            )
        if not summaries:
            continue
        series_entries.append(
            {
                "stepIndex": step_index,
                "timeKey": time_key,
                "metricKeys": metric_keys,
                "pointCount": len(ordered_rows),
                "points": points,
                "summaries": summaries,
            }
        )
    return series_entries[:4]


def _build_data_quality(
    *,
    data_tables: list[DataTable],
    table_summaries: list[dict[str, Any]],
    subtask_status: list[SubtaskStatus],
) -> list[dict[str, Any]]:
    quality: list[dict[str, Any]] = []
    for step_index, table in enumerate(data_tables, start=1):
        summary = table_summaries[step_index - 1] if step_index - 1 < len(table_summaries) else {}
        status = subtask_status[step_index - 1] if step_index - 1 < len(subtask_status) else None
        date_stats = summary.get("dateStats", {}) if isinstance(summary, dict) else {}
        date_columns, numeric_columns, _dimension_columns = _infer_table_roles(table)
        quality.append(
            {
                "stepIndex": step_index,
                "rowCount": table.rowCount,
                "columnCount": len(table.columns),
                "nullRatePct": float(summary.get("nullRatePct", 0.0) or 0.0) if isinstance(summary, dict) else 0.0,
                "dateColumns": date_columns,
                "numericColumns": numeric_columns,
                "status": status.status if status else "sufficient",
                "statusReason": status.reason if status else "",
                "dateCoverage": {key: value for key, value in date_stats.items() if isinstance(value, dict)},
            }
        )
    return quality


def _build_claim_coverage(
    *,
    requested_modes: list[str],
    data_tables: list[DataTable],
    artifacts: list[AnalysisArtifact],
    series: list[dict[str, Any]],
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifact_kinds = {artifact.kind for artifact in artifacts if artifact.rows}
    ranking_available = "ranking_breakdown" in artifact_kinds
    comparison_available = bool(comparisons) or "comparison_breakdown" in artifact_kinds
    distribution_available = "distribution_breakdown" in artifact_kinds
    snapshot_available = any(table.rowCount > 0 for table in data_tables) and (
        bool(facts)
        or bool(series)
        or any(any(_column_kind(table, column) == "number" for column in table.columns) for table in data_tables)
    )
    composition_available = any(
        any(token in column.lower() for token in ("share", "mix", "percent", "pct", "rate"))
        for table in data_tables
        for column in table.columns
    )
    multi_step_available = len([table for table in data_tables if table.rowCount > 0]) >= 2
    support_matrix = {
        "snapshot": (
            snapshot_available,
            ["observations", "facts"] if snapshot_available else [],
            "Absolute values are available from deterministic summaries or direct table observations."
            if snapshot_available
            else "No grounded absolute-value evidence was available.",
        ),
        "trend": (
            bool(series),
            ["series"] if series else [],
            "Time-ordered numeric series are available." if series else "No aligned time-based numeric series were available.",
        ),
        "comparison": (
            comparison_available,
            ["comparisons"] if comparison_available else [],
            "Deterministic comparisons or comparison artifacts are available."
            if comparison_available
            else "No deterministic prior/current comparison evidence was available.",
        ),
        "ranking": (
            ranking_available,
            ["rankingEvidence"] if ranking_available else [],
            "Deterministic ranking evidence is available." if ranking_available else "No authoritative ranking evidence was available.",
        ),
        "composition": (
            composition_available,
            ["observations"] if composition_available else [],
            "Composition-style percentage or share columns are available."
            if composition_available
            else "No deterministic composition/share evidence was available.",
        ),
        "distribution": (
            distribution_available,
            ["artifacts"] if distribution_available else [],
            "Distribution evidence is available." if distribution_available else "No deterministic distribution summary was available.",
        ),
        "multi_step_synthesis": (
            multi_step_available,
            ["executedSteps"] if multi_step_available else [],
            "Multiple non-empty executed steps are available for cross-step synthesis."
            if multi_step_available
            else "Only one populated step was available.",
        ),
    }

    supported_claims: list[dict[str, Any]] = []
    unsupported_claims: list[dict[str, Any]] = []
    for mode in requested_modes:
        supported, sources, reason = support_matrix.get(mode, (False, [], "No support metadata available."))
        entry = {"mode": mode, "sources": sources, "reason": reason}
        if supported:
            supported_claims.append(entry)
        else:
            unsupported_claims.append(entry)
    if not requested_modes:
        supported_claims.append(
            {
                "mode": "snapshot",
                "sources": ["observations"] if snapshot_available else [],
                "reason": "Defaulted to snapshot because no stronger analytical mode was requested.",
            }
        )
    return supported_claims, unsupported_claims


def _truncate_row(row: dict[str, Any], max_columns: int = _PROMPT_SAMPLE_COLUMN_CAP) -> dict[str, Any]:
    keys = list(row.keys())[:max_columns]
    return {key: row.get(key) for key in keys}


def _bounded_sample_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    bounded: list[dict[str, Any]] = []
    for item in raw[:_PROMPT_SAMPLE_ROW_CAP]:
        if isinstance(item, dict):
            bounded.append(_truncate_row(item))
    return bounded


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _ranking_evidence_payload(
    *,
    context: SynthesisContextPackage,
    artifacts: list[AnalysisArtifact],
) -> dict[str, Any] | None:
    ranking = next(
        (
            artifact
            for artifact in artifacts
            if artifact.kind == "ranking_breakdown" and artifact.rows and artifact.dimensionKey and artifact.valueKey
        ),
        None,
    )
    if ranking is None:
        return None

    dimension_key = ranking.dimensionKey or ""
    value_key = ranking.valueKey or ""
    rows = [row for row in ranking.rows if isinstance(row, dict)]
    if not rows or not dimension_key or not value_key:
        return None

    def _compact_rank_row(row: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            dimension_key: _json_safe(row.get(dimension_key)),
            value_key: _json_safe(row.get(value_key)),
        }
        rank_value = row.get("rank")
        if isinstance(rank_value, (int, float)) and not isinstance(rank_value, bool):
            payload["rank"] = int(rank_value)
        elif isinstance(rank_value, str):
            trimmed = rank_value.strip()
            if trimmed.isdigit():
                payload["rank"] = int(trimmed)
        return payload

    top_rows = [_compact_rank_row(row) for row in rows[:5]]
    bottom_rows = [_compact_rank_row(row) for row in rows[-3:]] if len(rows) > 5 else []

    entity_count = len(rows)
    for step in context.executedSteps:
        table_summary = step.tableSummary if isinstance(step.tableSummary, dict) else {}
        columns = table_summary.get("columns")
        if isinstance(columns, list) and dimension_key in columns and value_key in columns and step.rowCount > 0:
            entity_count = step.rowCount
            break

    return {
        "dimensionKey": dimension_key,
        "valueKey": value_key,
        "sortDir": "desc",
        "entityCount": entity_count,
        "topRows": top_rows,
        "bottomRows": bottom_rows,
    }


def _subtask_statuses(
    *,
    plan: list[QueryPlanStep] | None,
    results: list[SqlExecutionResult],
    table_summaries: list[dict[str, Any]],
) -> list[SubtaskStatus]:
    statuses: list[SubtaskStatus] = []
    plan_steps = plan or []
    max_steps = max(len(results), len(plan_steps))
    for index in range(max_steps):
        step_id = plan_steps[index].id if index < len(plan_steps) else f"step_{index + 1}"
        result = results[index] if index < len(results) else None
        summary = table_summaries[index] if index < len(table_summaries) else {}
        if result is None or result.rowCount <= 0:
            statuses.append(SubtaskStatus(id=step_id, status="insufficient", reason="Step returned no rows."))
            continue
        null_rate = float(summary.get("nullRatePct", 0.0) or 0.0)
        if null_rate >= 35.0:
            statuses.append(SubtaskStatus(id=step_id, status="limited", reason=f"High null concentration ({null_rate:.1f}%)."))
            continue
        statuses.append(SubtaskStatus(id=step_id, status="sufficient", reason="Step returned usable rows."))
    return statuses


def _derive_evidence_status(
    *,
    requested_claim_modes: list[str],
    supported_claims: list[dict[str, Any]],
    unsupported_claims: list[dict[str, Any]],
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
    subtask_status: list[SubtaskStatus],
) -> tuple[EvidenceStatus, str]:
    if requested_claim_modes and not supported_claims:
        requested = ", ".join(requested_claim_modes)
        return "insufficient", f"The requested analytical claim types could not be grounded: {requested}."
    if any(item.status == "insufficient" for item in subtask_status):
        return "limited", "At least one planned subtask returned insufficient evidence."
    if unsupported_claims:
        unsupported = ", ".join(str(item.get("mode", "")).strip() for item in unsupported_claims if item.get("mode"))
        if unsupported:
            return "limited", f"Some requested analytical claim types were not fully grounded: {unsupported}."
    weak_count = sum(1 for item in [*facts, *comparisons] if item.supportStatus == "weak")
    if weak_count > 0:
        return "limited", "Some derived claims are weak due to incomplete or weakly aligned evidence."
    if not supported_claims and not facts and not comparisons:
        return "insufficient", "No grounded analytical evidence could be derived from the returned results."
    return "sufficient", ""


def _claim_support(
    *,
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> list[ClaimSupport]:
    output: list[ClaimSupport] = []
    for item in facts:
        output.append(
            ClaimSupport(
                claimId=item.id,
                claimType="fact",
                supportStatus=item.supportStatus,
                reason=f"Derived from step {item.provenance.stepIndex} columns: {', '.join(item.provenance.columnRefs[:3])}.",
            )
        )
    for item in comparisons:
        step_refs = sorted({str(prov.stepIndex) for prov in item.provenance})
        output.append(
            ClaimSupport(
                claimId=item.id,
                claimType="comparison",
                supportStatus=item.supportStatus,
                reason=f"Comparison built from step(s) {', '.join(step_refs)}.",
            )
        )
    return output


def build_synthesis_context_package(
    *,
    plan: list[QueryPlanStep] | None,
    results: list[SqlExecutionResult],
    table_summaries: list[dict[str, Any]],
    artifacts: list[AnalysisArtifact],
    requested_claim_modes: list[str],
    supported_claims: list[dict[str, Any]],
    unsupported_claims: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    series: list[dict[str, Any]],
    data_quality: list[dict[str, Any]],
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
    evidence_status: EvidenceStatus,
    evidence_empty_reason: str,
    subtask_status: list[SubtaskStatus],
    interpretation_notes: list[str],
    caveats: list[str],
    headline: str,
    headline_refs: list[EvidenceReference],
    message: str,
) -> SynthesisContextPackage:
    plan_steps = plan or []
    synthesis_plan = [
        SynthesisPlanStep(id=step.id, goal=step.goal, dependsOn=step.dependsOn, independent=step.independent)
        for step in plan_steps
    ]
    executed_steps: list[SynthesisExecutedStep] = []
    for index, result in enumerate(results, start=1):
        step = plan_steps[index - 1] if index - 1 < len(plan_steps) else None
        table_summary = table_summaries[index - 1] if index - 1 < len(table_summaries) else {}
        plan_step = (
            SynthesisPlanStep(id=step.id, goal=step.goal, dependsOn=step.dependsOn, independent=step.independent)
            if step
            else SynthesisPlanStep(id=f"step_{index}", goal="No explicit plan step was available.", dependsOn=[], independent=True)
        )
        executed_steps.append(
            SynthesisExecutedStep(
                stepIndex=index,
                planStep=plan_step,
                executedSql=result.sql,
                rowCount=result.rowCount,
                tableSummary=table_summary,
            )
        )
    return SynthesisContextPackage(
        queryContext=SynthesisQueryContext(originalUserQuery=message),
        plan=synthesis_plan,
        executedSteps=executed_steps,
        availableVisualArtifacts=[
            SynthesisVisualArtifact(kind=artifact.kind, title=artifact.title, rowCount=len(artifact.rows))
            for artifact in artifacts
            if artifact.rows
        ],
        portfolioSummary=SynthesisPortfolioSummary(tableCount=len(results), totalRows=sum(result.rowCount for result in results)),
        requestedClaimModes=requested_claim_modes,
        supportedClaims=supported_claims,
        unsupportedClaims=unsupported_claims,
        observations=observations,
        series=series,
        dataQuality=data_quality,
        facts=facts[:_CONTEXT_FACT_CAP],
        comparisons=comparisons[:_CONTEXT_COMPARISON_CAP],
        evidenceStatus=evidence_status,
        evidenceEmptyReason=evidence_empty_reason,
        subtaskStatus=subtask_status,
        interpretationNotes=interpretation_notes[:5],
        caveats=caveats[:5],
        headline=headline,
        headlineEvidenceRefs=headline_refs,
    )


def _context_payload_for_prompt(
    context: SynthesisContextPackage,
    *,
    artifacts: list[AnalysisArtifact] | None = None,
) -> str:
    def _json_block(title: str, value: Any) -> str:
        return f"### {title} (JSON)\n```json\n{json.dumps(value, ensure_ascii=True, separators=(',', ':'))}\n```"

    def _compact_date_stats(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        compact: dict[str, Any] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            entry: dict[str, Any] = {}
            if "min" in value:
                entry["min"] = value["min"]
            if "max" in value:
                entry["max"] = value["max"]
            if "uniquePeriods" in value:
                entry["uniquePeriods"] = value["uniquePeriods"]
            if entry:
                compact[key] = entry
        return compact

    def _compact_table_summary(raw: Any, *, row_count: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        summary: dict[str, Any] = {
            "columnCount": raw.get("columnCount", 0),
            "columns": raw.get("columns", []),
            "nullRatePct": raw.get("nullRatePct", 0.0),
            "sampleRows": _bounded_sample_rows(raw.get("sampleRows")),
        }
        numeric_stats = raw.get("numericStats")
        if row_count > 3 and isinstance(numeric_stats, dict) and numeric_stats:
            summary["numericStats"] = numeric_stats
        date_stats = _compact_date_stats(raw.get("dateStats"))
        if date_stats:
            summary["dateStats"] = date_stats
        categorical_stats = raw.get("categoricalStats")
        if isinstance(categorical_stats, dict) and categorical_stats:
            summary["categoricalStats"] = categorical_stats
        comparison_signals = raw.get("comparisonSignals")
        if isinstance(comparison_signals, dict) and comparison_signals:
            summary["comparisonSignals"] = comparison_signals
        return summary

    def _metric_unit(metric: str, fallback: str = "number") -> str:
        lowered = metric.lower()
        if any(token in lowered for token in ("sales", "revenue", "spend", "amount", "cost")):
            return "currency"
        if any(token in lowered for token in ("pct", "percent", "share", "rate")):
            return "percent"
        if any(token in lowered for token in ("transaction", "count", "volume", "units", "qty")):
            return "count"
        return fallback

    def _round_abs_delta(metric: str, value: float, unit: str) -> float:
        if unit in {"currency", "percent"}:
            return round(float(value), 2)
        if _metric_unit(metric, fallback=unit) == "count":
            return float(int(round(float(value), 0)))
        return round(float(value), 2)

    def _period_label(raw_period: str) -> str:
        text = (raw_period or "").strip()
        if not text:
            return raw_period
        match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})$", text)
        if not match:
            return raw_period
        try:
            start = datetime.fromisoformat(match.group(1)).date()
            end = datetime.fromisoformat(match.group(2)).date()
        except ValueError:
            return raw_period

        if start.year == end.year and start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31:
            return f"{start.year}"

        if start.year == end.year:
            quarter = ((start.month - 1) // 3) + 1
            quarter_start_month = ((quarter - 1) * 3) + 1
            quarter_end_month = quarter_start_month + 2
            if (
                start.month == quarter_start_month
                and start.day == 1
                and end.month == quarter_end_month
                and end.day == monthrange(end.year, end.month)[1]
            ):
                return f"Q{quarter} {start.year}"

        if start.year == end.year and start.month == end.month and start.day == 1 and end.day == monthrange(end.year, end.month)[1]:
            return start.strftime("%b %Y")

        return raw_period

    fact_entries = context.facts[:_CONTEXT_FACT_CAP]
    comparison_entries = context.comparisons[:_CONTEXT_COMPARISON_CAP]
    fact_units = {item.metric: item.unit for item in fact_entries}

    payload: dict[str, Any] = {
        "plan": [{"id": step.id, "goal": step.goal} for step in context.plan],
        "executedSteps": [
            {
                "stepIndex": step.stepIndex,
                "rowCount": step.rowCount,
                "tableSummary": _compact_table_summary(step.tableSummary, row_count=step.rowCount),
            }
            for step in context.executedSteps
        ],
        "availableVisualArtifacts": [
            {"kind": item.kind, "title": item.title, "rowCount": item.rowCount}
            for item in context.availableVisualArtifacts
        ],
        "requestedClaimModes": context.requestedClaimModes,
        "supportedClaims": context.supportedClaims,
        "unsupportedClaims": context.unsupportedClaims,
        "observations": context.observations,
        "series": context.series,
        "dataQuality": context.dataQuality,
        "interpretationNotes": context.interpretationNotes,
        "caveats": context.caveats,
        "facts": [
            {
                "id": item.id,
                "metric": item.metric,
                "period": item.period,
                "value": item.value,
                "unit": item.unit,
                "grain": item.grain,
                "supportStatus": item.supportStatus,
                "salienceScore": item.salienceScore,
                "salienceRank": item.salienceRank,
                "salienceDriver": item.salienceDriver,
                "provenance": {
                    "stepIndex": item.provenance.stepIndex,
                    "timeWindow": item.provenance.timeWindow,
                },
            }
            for item in fact_entries
        ],
        "comparisons": [],
        "evidenceStatus": context.evidenceStatus,
        "subtaskStatus": [],
        "headline": context.headline,
        "headlineEvidenceRefs": [item.model_dump() for item in context.headlineEvidenceRefs],
    }
    ranking_evidence = _ranking_evidence_payload(context=context, artifacts=artifacts or [])
    if ranking_evidence is not None:
        payload["rankingEvidence"] = ranking_evidence

    for item in comparison_entries:
        unit = _metric_unit(item.metric, fallback=fact_units.get(item.metric, "number"))
        payload["comparisons"].append(
            {
                "id": item.id,
                "metric": item.metric,
                "priorPeriod": item.priorPeriod,
                "priorPeriodLabel": _period_label(item.priorPeriod),
                "currentPeriod": item.currentPeriod,
                "currentPeriodLabel": _period_label(item.currentPeriod),
                "priorValue": round(float(item.priorValue), 2) if unit in {"currency", "percent"} else float(item.priorValue),
                "currentValue": round(float(item.currentValue), 2) if unit in {"currency", "percent"} else float(item.currentValue),
                "absDelta": _round_abs_delta(item.metric, item.absDelta, unit),
                "pctDelta": round(float(item.pctDelta), 2) if item.pctDelta is not None else None,
                "supportStatus": item.supportStatus,
                "salienceScore": item.salienceScore,
                "salienceRank": item.salienceRank,
                "salienceDriver": item.salienceDriver,
                "provenance": [
                    {"stepIndex": provenance.stepIndex, "timeWindow": provenance.timeWindow}
                    for provenance in item.provenance
                ],
            }
        )

    if context.evidenceStatus != "sufficient" and context.evidenceEmptyReason:
        payload["evidenceEmptyReason"] = context.evidenceEmptyReason

    for item in context.subtaskStatus:
        entry: dict[str, Any] = {"id": item.id, "status": item.status}
        if item.status != "sufficient" and item.reason:
            entry["reason"] = item.reason
        payload["subtaskStatus"].append(entry)

    lines = [
        "## Synthesis Context Package (Hybrid)",
        "",
        f"EvidenceStatus: {payload['evidenceStatus']}",
        f"Headline: {json.dumps(payload.get('headline', ''), ensure_ascii=True)}",
        f"RequestedClaimModesCount: {len(payload['requestedClaimModes'])}",
        f"SupportedClaimsCount: {len(payload['supportedClaims'])}",
        f"FactsCount: {len(payload['facts'])}",
        f"ComparisonsCount: {len(payload['comparisons'])}",
        f"InterpretationNotesCount: {len(payload['interpretationNotes'])}",
        f"CaveatsCount: {len(payload['caveats'])}",
    ]
    if "evidenceEmptyReason" in payload:
        lines.append(f"EvidenceEmptyReason: {payload['evidenceEmptyReason']}")
    lines.append("")

    blocks: list[tuple[str, Any]] = [
        ("Plan", payload["plan"]),
        ("Subtask Status", payload["subtaskStatus"]),
        ("Available Visual Artifacts", payload["availableVisualArtifacts"]),
        ("Requested Claim Modes", payload["requestedClaimModes"]),
        ("Supported Claims", payload["supportedClaims"]),
        ("Unsupported Claims", payload["unsupportedClaims"]),
        ("Observations", payload["observations"]),
        ("Series", payload["series"]),
        ("Data Quality", payload["dataQuality"]),
        ("Interpretation Notes", payload["interpretationNotes"]),
        ("Caveats", payload["caveats"]),
        ("Ranking Evidence", payload.get("rankingEvidence")),
        ("Executed Steps", payload["executedSteps"]),
        ("Facts", payload["facts"]),
        ("Comparisons", payload["comparisons"]),
        ("Headline Evidence Refs", payload["headlineEvidenceRefs"]),
    ]
    for index, (title, value) in enumerate(blocks):
        lines.append(_json_block(title, value))
        if index < len(blocks) - 1:
            lines.append("")

    return "\n".join(lines).strip()
