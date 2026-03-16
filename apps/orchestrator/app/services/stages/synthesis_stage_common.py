from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from app.models import DataTable, PresentationIntent, TableColumnConfig, TableConfig

_OBJECTIVE_STOP_TOKENS = {"the", "and", "for", "with", "by", "of", "to", "in"}


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


def _first_column_by_kind(
    table: DataTable,
    kind: Literal["number", "date", "string"],
    *,
    exclude: set[str] | None = None,
) -> str | None:
    blocked = exclude or set()
    for column in table.columns:
        if column in blocked:
            continue
        if _column_kind(table, column) == kind:
            return column
    return None


def _normalize_objective_token(token: str) -> str:
    lowered = token.lower()
    aliases = {
        "average": "avg",
        "mean": "avg",
        "amount": "amt",
        "value": "amt",
        "transaction": "transactions",
        "count": "transactions",
        "volume": "transactions",
        "sales": "spend",
        "revenue": "spend",
    }
    return aliases.get(lowered, lowered)


def _objective_tokens(text: str) -> set[str]:
    tokens = {
        _normalize_objective_token(token)
        for token in re.split(r"[^a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in _OBJECTIVE_STOP_TOKENS
    }
    return {token for token in tokens if token}


def _resolve_objective_columns(table: DataTable, objectives: list[str]) -> list[str]:
    numeric_columns = [column for column in table.columns if _column_kind(table, column) == "number"]
    if len(numeric_columns) < 2:
        return []

    selected: list[str] = []
    used: set[str] = set()
    for objective in objectives:
        objective_tokens = _objective_tokens(objective)
        if not objective_tokens:
            continue
        best_column: str | None = None
        best_score = 0
        for column in numeric_columns:
            if column in used:
                continue
            column_tokens = _objective_tokens(column)
            overlap = len(objective_tokens.intersection(column_tokens))
            if overlap <= 0:
                continue
            if overlap > best_score:
                best_score = overlap
                best_column = column
        if best_column is None:
            continue
        used.add(best_column)
        selected.append(best_column)
    return selected


def _rank_column_key(metric_column: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", metric_column.lower()).strip("_")
    return f"rank_by_{normalized or 'metric'}"


def _row_number_ranks(rows: list[dict[str, Any]], metric_column: str) -> list[int]:
    scored: list[tuple[int, float]] = []
    for index, row in enumerate(rows):
        value = _as_float(row.get(metric_column))
        scored.append((index, value if value is not None else float("-inf")))
    ordered = sorted(scored, key=lambda item: item[1], reverse=True)
    rank_by_index: dict[int, int] = {}
    for rank, (index, _value) in enumerate(ordered, start=1):
        rank_by_index[index] = rank
    return [rank_by_index.get(index, len(rows)) for index in range(len(rows))]


def _table_column_index(columns: list[TableColumnConfig]) -> dict[str, TableColumnConfig]:
    return {column.key: column for column in columns}


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


def _ordered_assumptions(
    *,
    interpretation_notes: list[str],
    caveats: list[str],
    llm_assumptions: list[str],
    fallback_assumptions: list[str],
) -> list[str]:
    ordered: list[str] = []
    for bucket in (interpretation_notes, caveats, llm_assumptions, fallback_assumptions):
        for item in bucket:
            text = " ".join(str(item).split()).strip()
            if not text or text in ordered:
                continue
            ordered.append(text)
            if len(ordered) >= 5:
                return ordered
    return ordered


def _governed_table_intent(
    table: DataTable,
    preferred_style: Literal["simple", "ranked", "comparison"] | None = None,
) -> PresentationIntent:
    inferred_comparison = len(_infer_comparison_keys(table)) >= 2
    style = preferred_style
    if style == "comparison" and not inferred_comparison:
        style = None
    if style is None:
        style = "comparison" if inferred_comparison else ("ranked" if _first_column_by_kind(table, "number") else "simple")
    return PresentationIntent(displayType="table", tableStyle=style)
