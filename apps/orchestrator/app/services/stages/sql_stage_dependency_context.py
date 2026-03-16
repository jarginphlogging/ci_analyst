from __future__ import annotations

from typing import Any

from app.models import QueryPlanStep, SqlExecutionResult


def compact_context_value(value: Any, *, max_cell_chars: int = 80) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = " ".join(str(value).split()).strip()
    if len(text) <= max_cell_chars:
        return text
    return f"{text[: max_cell_chars - 3]}..."


def sample_dependency_rows(
    rows: list[dict[str, Any]],
    *,
    max_rows: int = 24,
    max_columns: int = 12,
    max_cell_chars: int = 80,
) -> tuple[list[dict[str, Any]], bool]:
    if not rows:
        return [], False

    total = len(rows)
    if total <= max_rows:
        selected = rows
        truncated = False
    else:
        head = max(1, max_rows // 2)
        tail = max(1, max_rows - head)
        selected = [*rows[:head], *rows[-tail:]]
        truncated = True

    sampled: list[dict[str, Any]] = []
    for row in selected:
        compact_row: dict[str, Any] = {}
        for column_index, (column, value) in enumerate(row.items()):
            if column_index >= max_columns:
                break
            compact_row[str(column)] = compact_context_value(value, max_cell_chars=max_cell_chars)
        sampled.append(compact_row)
    return sampled, truncated


def dependency_context_for_step(
    *,
    index: int,
    dependencies_by_index: dict[int, set[int]],
    plan: list[QueryPlanStep],
    results_by_index: dict[int, SqlExecutionResult],
    max_rows: int = 24,
    max_columns: int = 12,
    max_cell_chars: int = 80,
) -> list[dict[str, Any]]:
    dependency_indexes = sorted(dependencies_by_index.get(index, set()))
    if not dependency_indexes:
        return []

    context_items: list[dict[str, Any]] = []
    for dep_index in dependency_indexes:
        result = results_by_index.get(dep_index)
        if result is None:
            continue
        sampled_rows, truncated = sample_dependency_rows(
            result.rows,
            max_rows=max_rows,
            max_columns=max_columns,
            max_cell_chars=max_cell_chars,
        )
        context_items.append(
            {
                "stepId": plan[dep_index].id,
                "stepGoal": plan[dep_index].goal,
                "rowCount": result.rowCount,
                "columns": list(result.rows[0].keys()) if result.rows else [],
                "sampleRows": sampled_rows,
                "sampleTruncated": truncated,
            }
        )
    return context_items
