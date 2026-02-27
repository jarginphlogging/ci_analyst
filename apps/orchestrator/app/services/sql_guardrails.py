from __future__ import annotations

import re

from app.config import settings
from app.services.semantic_model import SemanticModel


FORBIDDEN_SQL_PATTERNS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bmerge\b",
    r"\bdrop\b",
    r"\btruncate\b",
    r"\balter\b",
    r"\bgrant\b",
    r"\brevoke\b",
]

TABLE_REF_PATTERN = re.compile(r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)", re.IGNORECASE)
LIMIT_PATTERN = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
CTE_NAME_PATTERN = re.compile(r"(?:\bwith\b|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", re.IGNORECASE)
TABLE_REF_REWRITE_PATTERN = re.compile(r"\b(from|join)\s+([a-zA-Z0-9_.\"]+)", re.IGNORECASE)


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _extract_table_references(sql: str) -> set[str]:
    refs: set[str] = set()
    for raw in TABLE_REF_PATTERN.findall(sql):
        cleaned = raw.strip().strip('"').lower()
        if not cleaned or cleaned.startswith("("):
            continue
        refs.add(cleaned)
    return refs


def _canonical_table_name(raw_ref: str) -> str:
    cleaned = raw_ref.strip().strip('"').lower()
    parts = [part.strip('"').strip() for part in cleaned.split(".") if part.strip()]
    return parts[-1] if parts else cleaned


def _rewrite_qualified_table_refs_for_sandbox(sql: str, model: SemanticModel) -> str:
    allowed = {table.name.lower() for table in model.tables}

    def _replace(match: re.Match[str]) -> str:
        keyword = match.group(1)
        raw_ref = match.group(2)
        canonical = _canonical_table_name(raw_ref)
        if canonical in allowed and canonical != raw_ref.strip().strip('"').lower():
            return f"{keyword} {canonical}"
        return match.group(0)

    return TABLE_REF_REWRITE_PATTERN.sub(_replace, sql)


def _extract_cte_names(sql: str) -> set[str]:
    return {name.lower() for name in CTE_NAME_PATTERN.findall(sql)}


def _enforce_select_only(sql: str) -> None:
    normalized = _normalize_sql(sql).lower()
    if not normalized.startswith("select") and not normalized.startswith("with"):
        raise ValueError("Generated SQL must start with SELECT or WITH.")
    for pattern in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, normalized):
            raise ValueError("Generated SQL contains forbidden statement.")


def _enforce_allowed_tables(sql: str, model: SemanticModel) -> None:
    allowed = {table.name.lower() for table in model.tables}
    cte_names = _extract_cte_names(sql)
    found = _extract_table_references(sql)
    if not found:
        raise ValueError("Generated SQL did not reference any allowlisted table.")
    blocked = [table for table in found if table not in allowed and table not in cte_names]
    if blocked:
        raise ValueError(f"Generated SQL referenced non-allowlisted table(s): {', '.join(blocked)}")


def _enforce_restricted_columns(sql: str, model: SemanticModel) -> None:
    lowered = sql.lower()
    for column in model.policy.restricted_columns:
        token = column.lower()
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            raise ValueError(f"Generated SQL referenced restricted column: {column}")


def _enforce_limit(sql: str, model: SemanticModel) -> str:
    stripped = sql.strip().rstrip(";")
    limit_match = LIMIT_PATTERN.search(stripped)

    if not limit_match:
        return f"{stripped}\nLIMIT {model.policy.default_row_limit}"

    current = int(limit_match.group(1))
    if current <= model.policy.max_row_limit:
        return stripped

    start, end = limit_match.span(1)
    return f"{stripped[:start]}{model.policy.max_row_limit}{stripped[end:]}"


def guard_sql(sql: str, model: SemanticModel) -> str:
    canonical_sql = sql
    # Sandbox SCA may emit fully qualified table refs (db.schema.table) while the
    # semantic-model allowlist stores canonical table names. Normalize only in sandbox mode.
    if settings.provider_mode == "sandbox":
        canonical_sql = _rewrite_qualified_table_refs_for_sandbox(sql, model)
    _enforce_select_only(canonical_sql)
    _enforce_allowed_tables(canonical_sql, model)
    _enforce_restricted_columns(canonical_sql, model)
    return _enforce_limit(canonical_sql, model)
