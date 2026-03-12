from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class SemanticPolicy:
    allowlisted_tables: tuple[str, ...]
    restricted_columns: tuple[str, ...]
    default_row_limit: int
    max_row_limit: int


def _default_policy_path() -> Path:
    env_path = settings.semantic_policy_path
    if env_path:
        return Path(env_path).expanduser()

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "semantic_guardrails.json"
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "Could not locate semantic guardrails config. Set SEMANTIC_POLICY_PATH to an absolute path."
    )


def _as_semantic_policy(payload: dict[str, Any]) -> SemanticPolicy:
    allowlisted_tables = tuple(
        str(value).strip().lower()
        for value in payload.get("allowlistedTables", [])
        if str(value).strip()
    )
    restricted_columns = tuple(
        str(value).strip()
        for value in payload.get("restrictedColumns", [])
        if str(value).strip()
    )
    default_row_limit = int(payload.get("defaultRowLimit", 1000))
    max_row_limit = int(payload.get("maxRowLimit", 5000))

    if not allowlisted_tables:
        raise RuntimeError("Semantic guardrails config has no allowlisted tables defined.")
    if default_row_limit <= 0 or max_row_limit <= 0:
        raise RuntimeError("Semantic guardrail row limits must be positive integers.")
    if default_row_limit > max_row_limit:
        raise RuntimeError("Semantic guardrail default row limit cannot exceed max row limit.")

    return SemanticPolicy(
        allowlisted_tables=allowlisted_tables,
        restricted_columns=restricted_columns,
        default_row_limit=default_row_limit,
        max_row_limit=max_row_limit,
    )


def load_semantic_policy(path: str | None = None) -> SemanticPolicy:
    policy_path = Path(path).expanduser() if path else _default_policy_path()
    if not policy_path.exists():
        raise RuntimeError(f"Semantic guardrails config not found at {policy_path}")

    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Semantic guardrails config file is not a JSON object.")
    return _as_semantic_policy(payload)
