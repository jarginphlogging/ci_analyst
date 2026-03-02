from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from app.models import AnalysisType, DataTable, JsonValue, PresentationPlan, VisualType

BindingType = Literal["text", "number", "boolean", "time", "time_or_number"]


@dataclass(frozen=True)
class PresentationBindingContract:
    analysis_type: AnalysisType
    visual_type: VisualType
    required_bindings: dict[str, BindingType]
    default_sort: list[str]


PRESENTATION_CONTRACTS: dict[AnalysisType, PresentationBindingContract] = {
    "trend_over_time": PresentationBindingContract(
        analysis_type="trend_over_time",
        visual_type="trend",
        required_bindings={
            "period_label": "text",
            "period_order": "time_or_number",
            "value": "number",
        },
        default_sort=["period_order:asc"],
    ),
    "ranking_top_n_bottom_n": PresentationBindingContract(
        analysis_type="ranking_top_n_bottom_n",
        visual_type="ranking",
        required_bindings={
            "entity_label": "text",
            "rank_index": "number",
            "value": "number",
        },
        default_sort=["rank_index:asc"],
    ),
    "comparison": PresentationBindingContract(
        analysis_type="comparison",
        visual_type="comparison",
        required_bindings={
            "entity_label": "text",
            "left_value": "number",
            "right_value": "number",
            "delta_value": "number",
        },
        default_sort=["delta_value:desc"],
    ),
    "composition_breakdown": PresentationBindingContract(
        analysis_type="composition_breakdown",
        visual_type="ranking",
        required_bindings={
            "entity_label": "text",
            "rank_index": "number",
            "value": "number",
        },
        default_sort=["rank_index:asc"],
    ),
    "aggregation_summary_stats": PresentationBindingContract(
        analysis_type="aggregation_summary_stats",
        visual_type="snapshot",
        required_bindings={
            "kpi_label": "text",
            "kpi_value": "number",
            "kpi_order": "number",
        },
        default_sort=["kpi_order:asc"],
    ),
    "point_in_time_snapshot": PresentationBindingContract(
        analysis_type="point_in_time_snapshot",
        visual_type="snapshot",
        required_bindings={
            "kpi_label": "text",
            "kpi_value": "number",
            "kpi_order": "number",
        },
        default_sort=["kpi_order:asc"],
    ),
    "period_over_period_change": PresentationBindingContract(
        analysis_type="period_over_period_change",
        visual_type="comparison",
        required_bindings={
            "entity_label": "text",
            "left_value": "number",
            "right_value": "number",
            "delta_value": "number",
        },
        default_sort=["delta_value:desc"],
    ),
    "anomaly_outlier_detection": PresentationBindingContract(
        analysis_type="anomaly_outlier_detection",
        visual_type="trend",
        required_bindings={
            "period_label": "text",
            "period_order": "time_or_number",
            "value": "number",
        },
        default_sort=["period_order:asc"],
    ),
    "drill_down_root_cause": PresentationBindingContract(
        analysis_type="drill_down_root_cause",
        visual_type="comparison",
        required_bindings={
            "entity_label": "text",
            "left_value": "number",
            "right_value": "number",
            "delta_value": "number",
        },
        default_sort=["delta_value:desc"],
    ),
    "correlation_relationship": PresentationBindingContract(
        analysis_type="correlation_relationship",
        visual_type="comparison",
        required_bindings={
            "entity_label": "text",
            "left_value": "number",
            "right_value": "number",
            "delta_value": "number",
        },
        default_sort=["delta_value:desc"],
    ),
    "cohort_analysis": PresentationBindingContract(
        analysis_type="cohort_analysis",
        visual_type="trend",
        required_bindings={
            "period_label": "text",
            "period_order": "time_or_number",
            "value": "number",
        },
        default_sort=["period_order:asc"],
    ),
    "distribution_histogram": PresentationBindingContract(
        analysis_type="distribution_histogram",
        visual_type="distribution",
        required_bindings={
            "bucket_label": "text",
            "bucket_order": "number",
            "value": "number",
        },
        default_sort=["bucket_order:asc"],
    ),
    "forecasting_projection": PresentationBindingContract(
        analysis_type="forecasting_projection",
        visual_type="trend",
        required_bindings={
            "period_label": "text",
            "period_order": "time_or_number",
            "value": "number",
        },
        default_sort=["period_order:asc"],
    ),
    "threshold_filter_segmentation": PresentationBindingContract(
        analysis_type="threshold_filter_segmentation",
        visual_type="table",
        required_bindings={},
        default_sort=[],
    ),
    "cumulative_running_total": PresentationBindingContract(
        analysis_type="cumulative_running_total",
        visual_type="trend",
        required_bindings={
            "period_label": "text",
            "period_order": "time_or_number",
            "value": "number",
        },
        default_sort=["period_order:asc"],
    ),
    "rate_ratio_efficiency": PresentationBindingContract(
        analysis_type="rate_ratio_efficiency",
        visual_type="comparison",
        required_bindings={
            "entity_label": "text",
            "left_value": "number",
            "right_value": "number",
            "delta_value": "number",
        },
        default_sort=["delta_value:desc"],
    ),
}


def get_presentation_contract(analysis_type: AnalysisType) -> PresentationBindingContract:
    return PRESENTATION_CONTRACTS[analysis_type]


def presentation_contract_prompt_block(analysis_type: AnalysisType) -> str:
    contract = get_presentation_contract(analysis_type)
    bindings = ", ".join(contract.required_bindings.keys()) or "(none required)"
    default_sort = ", ".join(contract.default_sort) or "(no required sort)"
    return (
        f"Primary visual contract for this response:\n"
        f"- analysisType: {contract.analysis_type}\n"
        f"- visualType: {contract.visual_type}\n"
        f"- required bindings: {bindings}\n"
        f"- required sort order entries (binding:asc|desc): {default_sort}\n"
        "If a string binding is unavailable in source columns, use const:<value>. "
        "Do not fabricate numeric values."
    )


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_boolean(value: JsonValue) -> bool:
    return isinstance(value, bool)


def _is_time(value: JsonValue) -> bool:
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


def _infer_column_type(rows: list[dict[str, JsonValue]], column: str) -> BindingType:
    values = [row.get(column) for row in rows[:200] if row.get(column) is not None]
    if not values:
        return "text"

    numeric = sum(1 for value in values if _is_number(value))
    boolean = sum(1 for value in values if _is_boolean(value))
    time_like = sum(1 for value in values if _is_time(value))
    total = max(1, len(values))

    if numeric / total >= 0.7:
        return "number"
    if boolean / total >= 0.7:
        return "boolean"
    if time_like / total >= 0.7:
        return "time"
    return "text"


def _matches_binding_type(inferred: BindingType, expected: BindingType) -> bool:
    if expected == "text":
        # Label bindings are rendered as strings in the UI and may come from
        # date or numeric dimensions (for example, month buckets).
        return inferred in {"text", "time", "number"}
    if expected == "time_or_number":
        return inferred in {"time", "number"}
    return inferred == expected


def _looks_like_rank_column(rows: list[dict[str, JsonValue]], column: str) -> bool:
    raw_values = [row.get(column) for row in rows[:200] if row.get(column) is not None]
    values = [value for value in raw_values if _is_number(value)]
    if not values:
        return False

    total = len(values)
    int_like = [value for value in values if float(value).is_integer() and float(value) > 0]
    if len(int_like) / total < 0.8:
        return False

    distinct = len({int(float(value)) for value in int_like})
    return distinct >= max(2, int(total * 0.5))


def _parse_sort_entries(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    parsed: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            parsed.append(text)
    return parsed


def validate_presentation_plan(
    *,
    raw_plan: Any,
    analysis_type: AnalysisType,
    data_tables: list[DataTable],
) -> tuple[PresentationPlan | None, list[str]]:
    contract = get_presentation_contract(analysis_type)
    issues: list[str] = []
    if not isinstance(raw_plan, dict):
        return None, ["Missing presentationPlan object in synthesis output."]

    table_id = str(raw_plan.get("tableId", "")).strip()
    table = next((item for item in data_tables if item.id == table_id), None)
    if table is None and table_id.startswith("step_"):
        suffix = table_id.split("_", 1)[1]
        table = next((item for item in data_tables if item.id == f"sql_step_{suffix}"), None)
    if table is None and table_id.startswith("sql_step_"):
        suffix = table_id.split("_", 2)[2] if table_id.count("_") >= 2 else ""
        if suffix.isdigit():
            index = int(suffix)
            if 1 <= index <= len(data_tables):
                table = data_tables[index - 1]
    if table is None and table_id.isdigit():
        index = int(table_id)
        if 1 <= index <= len(data_tables):
            table = data_tables[index - 1]
    if table is None:
        issues.append(f"presentationPlan.tableId '{table_id}' was not found in returned tables.")
        return None, issues

    bindings_raw = raw_plan.get("bindings")
    if not isinstance(bindings_raw, dict):
        issues.append("presentationPlan.bindings must be an object.")
        return None, issues

    normalized_bindings: dict[str, str] = {}
    for role, expected in contract.required_bindings.items():
        candidate = str(bindings_raw.get(role, "")).strip()
        if not candidate and role == "rank_index" and contract.visual_type == "ranking":
            normalized_bindings[role] = "__row_index__"
            continue
        if not candidate:
            issues.append(f"Missing required binding '{role}'.")
            continue
        normalized_bindings[role] = candidate
        if candidate == "__row_index__" and role == "rank_index":
            continue
        if candidate.startswith("const:"):
            literal = candidate[6:].strip()
            if role == "rank_index":
                normalized_bindings[role] = "__row_index__"
                continue
            if expected == "number":
                try:
                    float(literal)
                except ValueError:
                    issues.append(f"Binding '{role}' const value must be numeric.")
            elif expected == "time":
                if not _is_time(literal):
                    issues.append(f"Binding '{role}' const value must be ISO date/time.")
            elif expected == "time_or_number":
                is_num = True
                try:
                    float(literal)
                except ValueError:
                    is_num = False
                if not is_num and not _is_time(literal):
                    issues.append(f"Binding '{role}' const value must be numeric or ISO date/time.")
            continue
        if candidate not in table.columns:
            if role == "rank_index" and contract.visual_type == "ranking":
                normalized_bindings[role] = "__row_index__"
                continue
            issues.append(f"Binding '{role}' references unknown column '{candidate}'.")
            continue
        inferred = _infer_column_type(table.rows, candidate)
        if role == "rank_index" and contract.visual_type == "ranking" and inferred != "number":
            normalized_bindings[role] = "__row_index__"
            continue
        if not _matches_binding_type(inferred, expected):
            issues.append(
                f"Binding '{role}' expects {expected} but column '{candidate}' inferred as {inferred}."
            )

    if contract.visual_type == "ranking":
        rank_binding = normalized_bindings.get("rank_index")
        value_binding = normalized_bindings.get("value")
        if rank_binding and rank_binding != "__row_index__":
            if rank_binding == value_binding:
                normalized_bindings["rank_index"] = "__row_index__"
            elif not rank_binding.startswith("const:") and rank_binding in table.columns:
                if not _looks_like_rank_column(table.rows, rank_binding):
                    normalized_bindings["rank_index"] = "__row_index__"
        if "group_label" not in normalized_bindings:
            for candidate in ("category", "group", "segment", "tier", "band"):
                if candidate in table.columns and _infer_column_type(table.rows, candidate) == "text":
                    normalized_bindings["group_label"] = candidate
                    break

    raw_sort_entries = _parse_sort_entries(raw_plan.get("sort"))
    sort_entries: list[str] = []
    for entry in raw_sort_entries:
        if ":" not in entry:
            continue
        binding_name, direction = entry.split(":", 1)
        if direction not in {"asc", "desc"}:
            continue
        resolved_binding = binding_name
        if resolved_binding not in normalized_bindings:
            matched_binding = next(
                (
                    role
                    for role, reference in normalized_bindings.items()
                    if reference == binding_name
                ),
                None,
            )
            if matched_binding is None:
                continue
            resolved_binding = matched_binding
        sort_entries.append(f"{resolved_binding}:{direction}")

    if not sort_entries and contract.default_sort:
        sort_entries = list(contract.default_sort)

    if issues:
        return None, issues

    raw_visual_type = str(raw_plan.get("visualType", contract.visual_type)).strip().lower()
    visual_type = contract.visual_type if raw_visual_type == contract.visual_type else contract.visual_type
    title = str(raw_plan.get("title", "")).strip() or "Primary visual"
    scope_label = str(raw_plan.get("scopeLabel", "")).strip() or "Returned SQL output"
    notes = str(raw_plan.get("notes", "")).strip()

    return (
        PresentationPlan(
            analysisType=analysis_type,
            visualType=visual_type,
            tableId=table.id,
            title=title,
            scopeLabel=scope_label,
            bindings=normalized_bindings,
            sort=sort_entries,
            notes=notes,
        ),
        [],
    )


def table_fallback_presentation_plan(
    *,
    analysis_type: AnalysisType,
    data_tables: list[DataTable],
    reason: str,
) -> PresentationPlan | None:
    if not data_tables:
        return None
    first_table = data_tables[0]
    return PresentationPlan(
        analysisType=analysis_type,
        visualType="table",
        tableId=first_table.id,
        title="Primary data table",
        scopeLabel="Returned SQL output",
        bindings={},
        sort=[],
        notes=reason,
    )
