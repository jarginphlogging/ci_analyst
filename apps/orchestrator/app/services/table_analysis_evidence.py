from __future__ import annotations

from app.models import EvidenceRow, SqlExecutionResult
from app.services.table_analysis_common import (
    _comparison_columns,
    _profile_rows,
    _primary_result,
    _to_float,
)


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
