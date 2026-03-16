from __future__ import annotations

from typing import Any, Literal, cast

from app.models import ChartConfig, DataTable, PresentationIntent, PrimaryVisual, TableColumnConfig, TableConfig
from app.services.stages.synthesis_stage_common import (
    _comparison_keys_family_compatible,
    _column_kind,
    _first_column_by_kind,
    _governed_table_intent,
    _infer_comparison_keys,
    _is_comparison_like_column,
    _prettify,
    _rank_column_key,
    _resolve_objective_columns,
    _row_number_ranks,
    _table_column_index,
)


def _enforce_multi_objective_rank_contract(
    *,
    data_tables: list[DataTable],
    table_config: TableConfig | None,
    presentation_intent: PresentationIntent,
) -> None:
    if table_config is None or table_config.style != "ranked":
        return
    objectives = [item.strip() for item in presentation_intent.rankingObjectives if item and item.strip()]
    if len(objectives) < 2:
        return
    if not data_tables:
        return

    primary_table = data_tables[0]
    objective_columns = _resolve_objective_columns(primary_table, objectives)
    if len(objective_columns) < 2:
        return

    rank_columns: list[str] = []
    for metric_column in objective_columns[:2]:
        rank_column = _rank_column_key(metric_column)
        rank_columns.append(rank_column)
        ranks = _row_number_ranks(primary_table.rows, metric_column)
        for index, row in enumerate(primary_table.rows):
            row[rank_column] = ranks[index]
        if rank_column not in primary_table.columns:
            primary_table.columns.append(rank_column)

    existing_configs = _table_column_index(table_config.columns)
    rewritten_columns: list[TableColumnConfig] = []
    for rank_column in rank_columns:
        rewritten_columns.append(
            existing_configs.get(
                rank_column,
                TableColumnConfig(
                    key=rank_column,
                    label=_prettify(rank_column),
                    format="number",
                    align="right",
                ),
            )
        )

    for column in table_config.columns:
        if column.key in rank_columns:
            continue
        rewritten_columns.append(column)

    table_config.style = "simple"
    table_config.showRank = False
    table_config.sortBy = rank_columns[0]
    table_config.sortDir = "asc"
    table_config.columns = rewritten_columns


def _has_dual_rank_columns(*, data_tables: list[DataTable], table_config: TableConfig | None) -> bool:
    if table_config is not None:
        config_rank_columns = [column.key for column in table_config.columns if column.key.startswith("rank_by_")]
        if len(set(config_rank_columns)) >= 2:
            return True
    if not data_tables:
        return False
    table_rank_columns = [column for column in data_tables[0].columns if column.startswith("rank_by_")]
    return len(set(table_rank_columns)) >= 2


def _normalize_multi_objective_confidence_reason(
    *,
    confidence_reason: str,
    presentation_intent: PresentationIntent,
    data_tables: list[DataTable],
    table_config: TableConfig | None,
) -> str:
    objectives = [item.strip() for item in presentation_intent.rankingObjectives if item and item.strip()]
    if len(objectives) < 2:
        return confidence_reason
    if not _has_dual_rank_columns(data_tables=data_tables, table_config=table_config):
        return confidence_reason

    lowered = confidence_reason.lower()
    contradiction_patterns = (
        "only one objective",
        "single objective",
        "one objective",
        "single-sort evidence",
    )
    if any(pattern in lowered for pattern in contradiction_patterns):
        objective_text = " and ".join(objectives[:2])
        return (
            "Data is sufficient for dual-objective ranking with explicit rank columns for "
            f"{objective_text}."
        )
    return confidence_reason


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
