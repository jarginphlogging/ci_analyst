from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Literal, cast

from app.config import settings
from app.models import (
    AgentResponse,
    AnalysisArtifact,
    ChartConfig,
    ClaimSupport,
    ComparisonSignal,
    DataTable,
    EvidenceReference,
    EvidenceStatus,
    EvidenceRow,
    FactSignal,
    Insight,
    PresentationIntent,
    PrimaryVisual,
    QueryPlanStep,
    SummaryCard,
    SqlExecutionResult,
    SubtaskStatus,
    SynthesisContextPackage,
    SynthesisExecutedStep,
    SynthesisPlanStep,
    SynthesisPortfolioSummary,
    SynthesisQueryContext,
    SynthesisVisualArtifact,
    TableColumnConfig,
    TableConfig,
    TraceStep,
)
from app.prompts.templates import response_prompt
from app.services.llm_json import as_string_list
from app.services.llm_trace import llm_trace_stage
from app.services.stages.data_summarizer_stage import DataSummarizerStage
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_fact_comparison_signals,
    build_metric_points,
    detect_grain_mismatch,
    results_to_data_tables,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _prettify(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _is_time_value(value: Any) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return True
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _column_kind(table: DataTable, column: str) -> Literal["number", "date", "string"]:
    values = [row.get(column) for row in table.rows[:250] if row.get(column) is not None]
    if not values:
        return "string"
    numeric = sum(1 for value in values if _as_float(value) is not None)
    dates = sum(1 for value in values if _is_time_value(value))
    total = max(1, len(values))
    if numeric / total >= 0.7:
        return "number"
    if dates / total >= 0.7:
        return "date"
    return "string"


def _first_column_by_kind(table: DataTable, kind: Literal["number", "date", "string"], *, exclude: set[str] | None = None) -> str | None:
    blocked = exclude or set()
    for column in table.columns:
        if column in blocked:
            continue
        if _column_kind(table, column) == kind:
            return column
    return None


def _comparison_sort_key(column: str) -> tuple[int, int, int, str]:
    lowered = column.lower()
    year_match = re.search(r"(19|20)\d{2}", lowered)
    quarter_match = re.search(r"q([1-4])", lowered)
    if year_match:
        year = int(year_match.group(0))
        quarter = int(quarter_match.group(1)) if quarter_match else 5
        return (0, year, quarter, lowered)
    if any(token in lowered for token in ("prior", "previous", "last_year", "last year")):
        return (1, 0, 0, lowered)
    if any(token in lowered for token in ("current", "latest", "this_year", "this year")):
        return (2, 0, 0, lowered)
    return (3, 0, 0, lowered)


def _is_comparison_like_column(column: str) -> bool:
    lowered = column.lower()
    if re.search(r"(19|20)\d{2}", lowered):
        return True
    if re.search(r"\bq[1-4]\b", lowered):
        return True
    return any(
        token in lowered
        for token in ("prior", "previous", "last_year", "last year", "current", "latest", "baseline", "index")
    )


def _comparison_metric_family(column: str) -> str | None:
    tokens = [token for token in re.split(r"[^a-z0-9]+", column.lower()) if token]
    if len(tokens) < 2:
        return None

    removable_indexes = {
        index
        for index, token in enumerate(tokens)
        if re.fullmatch(r"(?:19|20)\d{2}", token)
        or re.fullmatch(r"y(?:19|20)\d{2}", token)
        or re.fullmatch(r"q[1-4]", token)
        or token in {"prior", "previous", "prev", "last", "baseline", "current", "latest", "this", "year", "index"}
    }
    family_tokens = [token for index, token in enumerate(tokens) if index not in removable_indexes]
    if not family_tokens:
        return None
    return "_".join(family_tokens)


def _comparison_keys_family_compatible(columns: list[str]) -> bool:
    families = [family for family in (_comparison_metric_family(column) for column in columns) if family is not None]
    if not families:
        return True
    return len(set(families)) == 1


def _infer_comparison_keys(table: DataTable, preferred: list[str] | None = None) -> list[str]:
    candidates = preferred or table.columns
    numeric = [
        column
        for column in candidates
        if column in table.columns and _column_kind(table, column) == "number" and _is_comparison_like_column(column)
    ]
    if len(numeric) < 2:
        return []
    scored = sorted(numeric, key=_comparison_sort_key)
    deduped = list(dict.fromkeys(scored))
    if not _comparison_keys_family_compatible(deduped):
        return []
    return deduped


def _sanitize_insights(raw: Any) -> list[Insight]:
    if not isinstance(raw, list):
        return []
    items: list[Insight] = []
    for index, entry in enumerate(raw[:4], start=1):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not title or not detail:
            continue
        importance = str(entry.get("importance", "medium")).lower()
        normalized_importance: Literal["high", "medium"] = "high" if importance == "high" else "medium"
        items.append(Insight(id=f"i{index}", title=title, detail=detail, importance=normalized_importance))
    return items


def _sanitize_summary_cards(raw: Any) -> list[SummaryCard]:
    if not isinstance(raw, list):
        return []
    cards: list[SummaryCard] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw[:3]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        value = str(entry.get("value", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not label or not value:
            continue
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        cards.append(SummaryCard(label=label, value=value, detail=detail))
    return cards


def _normalize_confidence(raw_confidence: str) -> Literal["high", "medium", "low"]:
    confidence = raw_confidence.lower().strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return cast(Literal["high", "medium", "low"], confidence)


def _default_questions(artifacts: list[AnalysisArtifact]) -> list[str]:
    if any(artifact.kind == "ranking_breakdown" for artifact in artifacts):
        return [
            "Can you break the top entities down by channel?",
            "Which entities moved most versus prior period?",
            "What percentage of total comes from the top decile?",
        ]
    if any(artifact.kind == "trend_breakdown" for artifact in artifacts):
        return [
            "Which segments are driving this trend?",
            "How does this compare to the same period last year?",
            "Where are change points or anomalies?",
        ]
    return [
        "Can you break this down by state and channel?",
        "How does this compare to the previous period?",
        "Which segments are driving the result?",
    ]


def _deterministic_answer(results: list[SqlExecutionResult]) -> str:
    if not results:
        return "I completed the governed pipeline but no usable rows were returned."
    total_rows = sum(result.rowCount for result in results)
    return f"I retrieved {total_rows} rows and prepared a governed summary with visual-ready data."


def _deterministic_why_it_matters() -> str:
    return "Insights are grounded in the retrieved SQL output, and visuals are validated before rendering."


def _default_chart_config(intent: PresentationIntent, table: DataTable) -> ChartConfig | None:
    chart_type = intent.chartType or "line"
    x = _first_column_by_kind(table, "date") or (table.columns[0] if table.columns else None)
    if x is None:
        return None
    y = _first_column_by_kind(table, "number", exclude={x})
    if y is None:
        return None
    series = _first_column_by_kind(table, "string", exclude={x, y})
    return ChartConfig(
        type=chart_type,
        x=x,
        y=y,
        series=series,
        xLabel=_prettify(x),
        yLabel=_prettify(y),
        yFormat="currency" if any(token in y.lower() for token in ("sales", "revenue", "amount", "spend", "cost")) else "number",
    )


def _default_table_config(intent: PresentationIntent, table: DataTable) -> TableConfig:
    style = intent.tableStyle or "simple"
    columns = [
        TableColumnConfig(
            key=column,
            label=_prettify(column),
            format=(
                "number"
                if _column_kind(table, column) == "number"
                else "date"
                if _column_kind(table, column) == "date"
                else "string"
            ),
            align="right" if _column_kind(table, column) == "number" else "left",
        )
        for column in table.columns
    ]
    numeric_sort = _first_column_by_kind(table, "number")
    config = TableConfig(
        style=style,
        columns=columns,
        sortBy=numeric_sort,
        sortDir="desc" if numeric_sort else None,
        showRank=style == "ranked",
    )
    if style != "comparison":
        return config

    comparison_keys = _infer_comparison_keys(table)
    if len(comparison_keys) < 2:
        config.style = "simple"
        config.showRank = False
        return config
    baseline_key = comparison_keys[0]
    config.comparisonMode = "baseline"
    config.comparisonKeys = comparison_keys
    config.baselineKey = baseline_key
    config.deltaPolicy = "both"
    config.maxComparandsBeforeChartSwitch = 6
    delta_column = next((column for column in table.columns if "delta" in column.lower() or "change" in column.lower()), None)
    if delta_column and _column_kind(table, delta_column) == "number":
        config.sortBy = delta_column
        config.sortDir = "desc"
    return config


def _governed_table_intent(table: DataTable, preferred_style: Literal["simple", "ranked", "comparison"] | None = None) -> PresentationIntent:
    inferred_comparison = len(_infer_comparison_keys(table)) >= 2
    style = preferred_style
    if style == "comparison" and not inferred_comparison:
        style = None
    if style is None:
        style = "comparison" if inferred_comparison else ("ranked" if _first_column_by_kind(table, "number") else "simple")
    return PresentationIntent(displayType="table", tableStyle=style)


def _sanitize_chart_config(raw: Any, table: DataTable) -> ChartConfig | None:
    if not isinstance(raw, dict):
        return None
    chart_type = str(raw.get("type", "")).strip().lower().replace("-", "_")
    if chart_type not in {"line", "bar", "stacked_bar", "stacked_area", "grouped_bar"}:
        return None
    x = str(raw.get("x", "")).strip()
    if x not in table.columns:
        return None
    y_raw = raw.get("y")
    if isinstance(y_raw, list):
        y = [str(item).strip() for item in y_raw if str(item).strip()]
        if not y:
            return None
        if any(column not in table.columns for column in y):
            return None
        y_value: str | list[str] = y
    else:
        y_str = str(y_raw or "").strip()
        if y_str not in table.columns:
            return None
        y_value = y_str
    series = str(raw.get("series", "")).strip() or None
    if series and series not in table.columns:
        return None

    distinct_x = len({row.get(x) for row in table.rows if row.get(x) is not None})
    if distinct_x < 3:
        return None
    if series:
        series_count = len({row.get(series) for row in table.rows if row.get(series) is not None})
        if series_count > 10:
            return None

    y_format = str(raw.get("yFormat", "number")).strip().lower()
    if y_format not in {"currency", "number", "percent"}:
        y_format = "number"
    return ChartConfig(
        type=cast(Literal["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"], chart_type),
        x=x,
        y=y_value,
        series=series,
        xLabel=str(raw.get("xLabel", "")).strip() or _prettify(x),
        yLabel=str(raw.get("yLabel", "")).strip() or _prettify(y_value[0] if isinstance(y_value, list) else y_value),
        yFormat=cast(Literal["currency", "number", "percent"], y_format),
    )


def _sanitize_table_config(raw: Any, table: DataTable) -> TableConfig | None:
    if not isinstance(raw, dict):
        return None
    style = str(raw.get("style", "simple")).strip().lower()
    if style not in {"simple", "ranked", "comparison"}:
        style = "simple"

    raw_columns = raw.get("columns")
    columns: list[TableColumnConfig] = []
    if isinstance(raw_columns, list):
        for item in raw_columns:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if key not in table.columns:
                continue
            fmt = str(item.get("format", "string")).strip().lower()
            if fmt not in {"currency", "number", "percent", "date", "string"}:
                fmt = "string"
            align = str(item.get("align", "left")).strip().lower()
            if align not in {"left", "right"}:
                align = "left"
            columns.append(
                TableColumnConfig(
                    key=key,
                    label=str(item.get("label", "")).strip() or _prettify(key),
                    format=cast(Literal["currency", "number", "percent", "date", "string"], fmt),
                    align=cast(Literal["left", "right"], align),
                )
            )
    if not columns:
        return None

    sort_by = str(raw.get("sortBy", "")).strip() or None
    if sort_by and sort_by not in table.columns:
        sort_by = None
    sort_dir_raw = str(raw.get("sortDir", "")).strip().lower()
    sort_dir = cast(Literal["asc", "desc"], sort_dir_raw) if sort_dir_raw in {"asc", "desc"} else None
    config = TableConfig(
        style=cast(Literal["simple", "ranked", "comparison"], style),
        columns=columns,
        sortBy=sort_by,
        sortDir=sort_dir,
        showRank=bool(raw.get("showRank", style == "ranked")),
    )
    if style != "comparison":
        return config

    comparison_mode_raw = str(raw.get("comparisonMode", "baseline")).strip().lower()
    comparison_mode = cast(Literal["baseline", "pairwise", "index"], comparison_mode_raw) if comparison_mode_raw in {
        "baseline",
        "pairwise",
        "index",
    } else "baseline"
    raw_keys = raw.get("comparisonKeys")
    comparison_keys: list[str] = []
    if isinstance(raw_keys, list):
        for item in raw_keys:
            key = str(item).strip()
            if key and key in table.columns and _column_kind(table, key) == "number" and _is_comparison_like_column(key):
                comparison_keys.append(key)
    comparison_keys = list(dict.fromkeys(comparison_keys))
    if len(comparison_keys) >= 2 and not _comparison_keys_family_compatible(comparison_keys):
        comparison_keys = []
    if len(comparison_keys) < 2:
        comparison_keys = _infer_comparison_keys(table, [column.key for column in columns])
    if len(comparison_keys) < 2:
        return None

    baseline_raw = str(raw.get("baselineKey", "")).strip() or None
    baseline_key = baseline_raw if baseline_raw in comparison_keys else comparison_keys[0]
    delta_policy_raw = str(raw.get("deltaPolicy", "both")).strip().lower()
    delta_policy = cast(Literal["abs", "pct", "both"], delta_policy_raw) if delta_policy_raw in {
        "abs",
        "pct",
        "both",
    } else "both"
    threshold_raw = raw.get("maxComparandsBeforeChartSwitch")
    threshold = int(threshold_raw) if isinstance(threshold_raw, int) and threshold_raw > 0 else 6

    config.comparisonMode = comparison_mode
    config.comparisonKeys = comparison_keys
    config.baselineKey = baseline_key
    config.deltaPolicy = delta_policy
    config.maxComparandsBeforeChartSwitch = threshold
    return config

def _resolve_visual_config(
    *,
    llm_payload: dict[str, Any],
    presentation_intent: PresentationIntent,
    data_tables: list[DataTable],
) -> tuple[ChartConfig | None, TableConfig | None, list[str]]:
    issues: list[str] = []
    primary_table = data_tables[0] if data_tables else None
    if primary_table is None:
        return None, None, ["No data table available for visual configuration."]

    chart_config: ChartConfig | None = None
    table_config: TableConfig | None = None
    if presentation_intent.displayType == "chart":
        chart_config = _sanitize_chart_config(llm_payload.get("chartConfig"), primary_table)
        if chart_config is None:
            fallback_chart = _default_chart_config(presentation_intent, primary_table)
            if fallback_chart is not None:
                chart_config = fallback_chart
                issues.append("Chart config fallback applied from deterministic defaults.")
            else:
                table_config = _sanitize_table_config(llm_payload.get("tableConfig"), primary_table)
                if table_config is None:
                    table_config = _default_table_config(_governed_table_intent(primary_table), primary_table)
                issues.append("Chart unavailable for result shape; downgraded to table.")
    elif presentation_intent.displayType == "table":
        table_config = _sanitize_table_config(llm_payload.get("tableConfig"), primary_table)
        if table_config is None:
            table_config = _default_table_config(_governed_table_intent(primary_table, presentation_intent.tableStyle), primary_table)
    else:
        # Inline intent: do not force a visual unless model provides a valid one.
        chart_config = _sanitize_chart_config(llm_payload.get("chartConfig"), primary_table)
        if chart_config is None:
            table_config = None
    return chart_config, table_config, issues


def _primary_visual_from_config(chart_config: ChartConfig | None, table_config: TableConfig | None) -> PrimaryVisual | None:
    if chart_config is not None:
        visual_type = (
            "trend"
            if chart_config.type in {"line", "stacked_area"}
            else "comparison"
            if chart_config.type == "grouped_bar"
            else "ranking"
        )
        return PrimaryVisual(
            title=f"{_prettify(chart_config.y[0] if isinstance(chart_config.y, list) else chart_config.y)} by {_prettify(chart_config.x)}",
            description="Validated chart generated from retrieved SQL output.",
            visualType=cast(Literal["trend", "ranking", "comparison", "distribution", "snapshot", "table"], visual_type),
        )
    if table_config is not None:
        return PrimaryVisual(
            title="Primary data table",
            description="Validated table generated from retrieved SQL output.",
            visualType="table",
        )
    return None


_PROMPT_SAMPLE_ROW_CAP = 3
_PROMPT_SAMPLE_COLUMN_CAP = 8
_CONTEXT_FACT_CAP = 20
_CONTEXT_COMPARISON_CAP = 14


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
            if artifact.kind == "ranking_breakdown"
            and artifact.rows
            and artifact.dimensionKey
            and artifact.valueKey
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
            statuses.append(
                SubtaskStatus(
                    id=step_id,
                    status="limited",
                    reason=f"High null concentration ({null_rate:.1f}%).",
                )
            )
            continue
        statuses.append(SubtaskStatus(id=step_id, status="sufficient", reason="Step returned usable rows."))
    return statuses


def _derive_evidence_status(
    *,
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
    subtask_status: list[SubtaskStatus],
) -> tuple[EvidenceStatus, str]:
    if not facts and not comparisons:
        return "insufficient", "No comparable facts could be derived from returned columns and periods."
    if any(item.status == "insufficient" for item in subtask_status):
        return "limited", "At least one planned subtask returned insufficient evidence."
    weak_count = sum(1 for item in [*facts, *comparisons] if item.supportStatus == "weak")
    if weak_count > 0:
        return "limited", "Some derived claims are weak due to incomplete or weakly aligned evidence."
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


def _deterministic_headline(
    *,
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> tuple[str, list[EvidenceReference]]:
    if comparisons:
        top = comparisons[0]
        pct_text = f" ({top.pctDelta:+.1f}%)" if top.pctDelta is not None else ""
        text = (
            f"{_prettify(top.metric)} moved {top.absDelta:+,.2f}{pct_text}, "
            f"from {top.priorValue:,.2f} in {top.priorPeriod} to {top.currentValue:,.2f} in {top.currentPeriod}."
        )
        return text, [EvidenceReference(refType="comparison", refId=top.id)]
    if facts:
        top = facts[0]
        text = f"{_prettify(top.metric)} is {top.value:,.2f} for {top.period}."
        return text, [EvidenceReference(refType="fact", refId=top.id)]
    return "", []


def _attach_artifact_evidence(
    *,
    artifacts: list[AnalysisArtifact],
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> list[AnalysisArtifact]:
    fact_by_metric: dict[str, list[FactSignal]] = {}
    for fact in facts:
        fact_by_metric.setdefault(fact.metric.lower(), []).append(fact)
    comparison_by_metric: dict[str, list[ComparisonSignal]] = {}
    for comparison in comparisons:
        comparison_by_metric.setdefault(comparison.metric.lower(), []).append(comparison)

    enriched: list[AnalysisArtifact] = []
    for artifact in artifacts:
        refs: list[EvidenceReference] = []
        if artifact.kind == "comparison_breakdown":
            dimension_key = artifact.dimensionKey or "metric"
            for row in artifact.rows[:8]:
                token = str(row.get(dimension_key, "")).strip().lower()
                for comparison in comparison_by_metric.get(token, [])[:2]:
                    refs.append(EvidenceReference(refType="comparison", refId=comparison.id))
        if not refs and artifact.valueKey:
            for fact in fact_by_metric.get(artifact.valueKey.lower(), [])[:2]:
                refs.append(EvidenceReference(refType="fact", refId=fact.id))
        if not refs and comparisons:
            refs.append(EvidenceReference(refType="comparison", refId=comparisons[0].id))
        if not refs and facts:
            refs.append(EvidenceReference(refType="fact", refId=facts[0].id))

        best_score = 0.0
        best_rank: int | None = None
        best_driver = None
        best_support = None
        for ref in refs:
            if ref.refType == "fact":
                source = next((item for item in facts if item.id == ref.refId), None)
            else:
                source = next((item for item in comparisons if item.id == ref.refId), None)
            if source is None:
                continue
            score = float(getattr(source, "salienceScore", 0.0) or 0.0)
            if score >= best_score:
                best_score = score
                best_rank = getattr(source, "salienceRank", None)
                best_driver = getattr(source, "salienceDriver", None)
                best_support = getattr(source, "supportStatus", None)

        enriched.append(
            artifact.model_copy(
                update={
                    "evidenceRefs": refs[:6],
                    "salienceScore": round(best_score, 6) if best_score else None,
                    "salienceRank": best_rank,
                    "salienceDriver": best_driver,
                    "supportStatus": best_support,
                }
            )
        )
    return enriched


def _context_payload_for_prompt(
    context: SynthesisContextPackage,
    *,
    artifacts: list[AnalysisArtifact] | None = None,
) -> str:
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
                    {
                        "stepIndex": provenance.stepIndex,
                        "timeWindow": provenance.timeWindow,
                    }
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

    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json
        self._data_summarizer = DataSummarizerStage()

    async def build_fast_response(
        self,
        *,
        message: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            plan=plan,
            presentation_intent=presentation_intent,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=False,
        )

    async def build_response(
        self,
        *,
        message: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            plan=plan,
            presentation_intent=presentation_intent,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=True,
        )

    def _synthesis_context_package(
        self,
        *,
        message: str,
        plan: list[QueryPlanStep] | None,
        results: list[SqlExecutionResult],
        artifacts: list[AnalysisArtifact],
        facts: list[FactSignal],
        comparisons: list[ComparisonSignal],
        evidence_status: EvidenceStatus,
        evidence_empty_reason: str,
        subtask_status: list[SubtaskStatus],
        headline: str,
        headline_refs: list[EvidenceReference],
    ) -> SynthesisContextPackage:
        plan_steps = plan or []
        table_summaries = self._data_summarizer.summarize_tables(results=results, message=message)
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
            portfolioSummary=SynthesisPortfolioSummary(
                tableCount=len(results),
                totalRows=sum(result.rowCount for result in results),
            ),
            facts=facts[:_CONTEXT_FACT_CAP],
            comparisons=comparisons[:_CONTEXT_COMPARISON_CAP],
            evidenceStatus=evidence_status,
            evidenceEmptyReason=evidence_empty_reason,
            subtaskStatus=subtask_status,
            headline=headline,
            headlineEvidenceRefs=headline_refs,
        )

    async def _build_response(
        self,
        *,
        message: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
        with_llm: bool,
    ) -> AgentResponse:
        _ = prior_assumptions
        evidence = build_evidence_rows(results, message=message)
        raw_artifacts = build_analysis_artifacts(results, message=message)
        facts, comparisons = build_fact_comparison_signals(results, message=message)
        artifacts = _attach_artifact_evidence(artifacts=raw_artifacts, facts=facts, comparisons=comparisons)
        table_summaries = self._data_summarizer.summarize_tables(results=results, message=message)
        subtask_status = _subtask_statuses(plan=plan, results=results, table_summaries=table_summaries)
        evidence_status, evidence_empty_reason = _derive_evidence_status(
            facts=facts,
            comparisons=comparisons,
            subtask_status=subtask_status,
        )
        headline, headline_refs = _deterministic_headline(facts=facts, comparisons=comparisons)
        claim_support = _claim_support(facts=facts, comparisons=comparisons)
        metrics = build_metric_points(results, evidence, message=message)
        data_tables = results_to_data_tables(results)
        synthesis_context = self._synthesis_context_package(
            message=message,
            plan=plan,
            results=results,
            artifacts=artifacts,
            facts=facts,
            comparisons=comparisons,
            evidence_status=evidence_status,
            evidence_empty_reason=evidence_empty_reason,
            subtask_status=subtask_status,
            headline=headline,
            headline_refs=headline_refs,
        )
        result_summary = _context_payload_for_prompt(synthesis_context, artifacts=artifacts)

        llm_payload: dict[str, Any] = {}
        if with_llm:
            try:
                system_prompt, user_prompt = response_prompt(
                    message,
                    json.dumps(presentation_intent.model_dump(), ensure_ascii=True),
                    result_summary,
                    history,
                )
                with llm_trace_stage(
                    "synthesis_final",
                    {"planStepCount": len(plan or []), "historyDepth": len(history)},
                ):
                    llm_payload = await self._ask_llm_json(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        max_tokens=settings.real_llm_max_tokens,
                    )
            except Exception:
                if settings.provider_mode in {"sandbox", "prod"}:
                    raise
                llm_payload = {}

        answer = str(llm_payload.get("answer", "")).strip() or _deterministic_answer(results)
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or _deterministic_why_it_matters()
        confidence_default = "medium" if with_llm else "high"
        confidence = _normalize_confidence(str(llm_payload.get("confidence", confidence_default)))
        confidence_reason = str(llm_payload.get("confidenceReason", "")).strip()
        if not confidence_reason:
            llm_assumptions = as_string_list(llm_payload.get("assumptions"), max_items=1)
            if llm_assumptions:
                confidence_reason = llm_assumptions[0]
        if not confidence_reason:
            confidence_reason = why_it_matters

        chart_config, table_config, _visual_issues = _resolve_visual_config(
            llm_payload=llm_payload,
            presentation_intent=presentation_intent,
            data_tables=data_tables,
        )
        insights = _sanitize_insights(llm_payload.get("insights")) or [
            Insight(id="i1", title="Primary data is ready", detail="Tabular evidence is available for inspection and export.", importance="medium")
        ]
        summary_cards = _sanitize_summary_cards(llm_payload.get("summaryCards"))
        if not summary_cards:
            summary_cards = [
                SummaryCard(label=metric.label, value=f"{metric.value:,.2f}" if metric.unit != "count" else f"{metric.value:,.0f}")
                for metric in metrics[:3]
            ]
        suggested_questions = as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions(artifacts)

        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=5)
        grain_mismatch = detect_grain_mismatch(results, message)
        if grain_mismatch:
            requested, detected = grain_mismatch
            if confidence == "high":
                confidence = "medium"

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and presentation path",
                summary="Validated relevance and generated a bounded delegation plan with presentation intent.",
                status="done",
            ),
            TraceStep(
                id="t2",
                title="Generate and execute governed SQL",
                summary="Generated SQL with allowlist and restricted-column guardrails, then executed warehouse steps.",
                status="done",
                sql=results[0].sql if results else None,
            ),
            TraceStep(
                id="t3",
                title="Synthesize narrative and visual config",
                summary=(
                    "Built deterministic narrative and visual fallback from retrieved data."
                    if not with_llm
                    else "Combined deterministic summaries with constrained narrative synthesis and validated visual config."
                ),
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence,
            confidenceReason=confidence_reason,
            whyItMatters=why_it_matters,
            presentationIntent=presentation_intent,
            chartConfig=chart_config,
            tableConfig=table_config,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights[:4],
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:5],
            trace=trace,
            summaryCards=summary_cards,
            primaryVisual=_primary_visual_from_config(chart_config, table_config),
            dataTables=data_tables,
            artifacts=artifacts,
            facts=facts[:_CONTEXT_FACT_CAP],
            comparisons=comparisons[:_CONTEXT_COMPARISON_CAP],
            evidenceStatus=evidence_status,
            evidenceEmptyReason=evidence_empty_reason,
            subtaskStatus=subtask_status,
            claimSupport=claim_support[:40],
            headline=headline,
            headlineEvidenceRefs=headline_refs,
        )


def build_incremental_answer_deltas(fast_answer: str, final_answer: str) -> list[str]:
    _ = fast_answer
    final = final_answer.strip()
    if not final:
        return [""]
    return [f"{token} " for token in final.split(" ")]
