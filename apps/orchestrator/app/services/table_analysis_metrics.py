from __future__ import annotations

from statistics import mean

from app.models import EvidenceRow, MetricPoint, SqlExecutionResult
from app.services.table_analysis_common import (
    _column_label,
    _preferred_metric,
    _profile_rows,
    _primary_result,
    _to_float,
)


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
