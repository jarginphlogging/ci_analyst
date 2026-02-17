from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, Union

from app.models import DataTable, EvidenceRow, MetricPoint, SqlExecutionResult

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


def _find_column(columns: list[str], candidates: list[str]) -> Optional[str]:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        for lower, original in lowered.items():
            if candidate in lower:
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


def build_evidence_rows(results: list[SqlExecutionResult], max_rows: int = 8) -> list[EvidenceRow]:
    if not results:
        return []

    rows = results[0].rows
    if not rows:
        return []

    columns = list(rows[0].keys())
    segment_col = _find_column(columns, ["segment", "region", "corridor", "client_segment", "product", "channel"])
    prior_col = _find_column(columns, ["prior", "previous", "baseline", "prev"])
    current_col = _find_column(columns, ["current", "latest", "curr"])
    change_col = _find_column(columns, ["changebps", "delta_bps", "delta", "change"])
    contribution_col = _find_column(columns, ["contribution", "share", "impact"])

    evidence: list[EvidenceRow] = []
    for index, row in enumerate(rows[:max_rows]):
        segment = str(row.get(segment_col, f"Segment {index + 1}")) if segment_col else f"Segment {index + 1}"
        prior = _to_float(row.get(prior_col)) if prior_col else None
        current = _to_float(row.get(current_col)) if current_col else None
        change = _to_float(row.get(change_col)) if change_col else None
        contribution = _to_float(row.get(contribution_col)) if contribution_col else None

        prior_value = prior if prior is not None else 0.0
        current_value = current if current is not None else prior_value

        if change is None:
            if prior is not None and current is not None:
                change = (current - prior) * (10000 if abs(prior) <= 1.5 and abs(current) <= 1.5 else 1)
            else:
                change = 0.0

        evidence.append(
            EvidenceRow(
                segment=segment,
                prior=prior_value,
                current=current_value,
                changeBps=float(change),
                contribution=float(contribution or 0.0),
            )
        )

    return evidence


def build_metric_points(results: list[SqlExecutionResult], evidence: list[EvidenceRow]) -> list[MetricPoint]:
    total_rows = sum(result.rowCount for result in results)

    metrics: list[MetricPoint] = [
        MetricPoint(label="Rows Retrieved", value=float(total_rows), delta=0.0, unit="count")
    ]

    if evidence:
        average_change = sum(row.changeBps for row in evidence) / len(evidence)
        max_move = max(abs(row.changeBps) for row in evidence)
        metrics.append(MetricPoint(label="Average Segment Delta", value=average_change, delta=average_change, unit="bps"))
        metrics.append(MetricPoint(label="Largest Segment Move", value=max_move, delta=max_move, unit="bps"))
        return metrics

    if results and results[0].rows:
        first_row = results[0].rows[0]
        numeric_values = [float(value) for value in first_row.values() if _is_numeric(value)]
        if numeric_values:
            metrics.append(MetricPoint(label="Row 1 Numeric Sum", value=sum(numeric_values), delta=0.0, unit="count"))
            metrics.append(
                MetricPoint(
                    label="Row 1 Numeric Mean",
                    value=sum(numeric_values) / len(numeric_values),
                    delta=0.0,
                    unit="count",
                )
            )

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

