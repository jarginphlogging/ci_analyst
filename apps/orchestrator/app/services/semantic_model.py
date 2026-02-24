from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import settings


@dataclass(frozen=True)
class SemanticTable:
    name: str
    description: str
    dimensions: list[str]
    metrics: list[str]


@dataclass(frozen=True)
class JoinRule:
    left: str
    right: str
    keys: list[str]


@dataclass(frozen=True)
class SemanticPolicy:
    restricted_columns: list[str]
    default_row_limit: int
    max_row_limit: int


@dataclass(frozen=True)
class SemanticModel:
    version: str
    description: str
    tables: list[SemanticTable]
    join_rules: list[JoinRule]
    policy: SemanticPolicy


def _default_model_path() -> Path:
    env_path = settings.semantic_model_path
    if env_path:
        return Path(env_path).expanduser()

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "semantic-model" / "models" / "banking-core.v1.json"
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "Could not locate semantic model file. Set SEMANTIC_MODEL_PATH to an absolute path."
    )


def _as_semantic_model(payload: dict[str, Any]) -> SemanticModel:
    tables = [
        SemanticTable(
            name=str(table["name"]),
            description=str(table.get("description", "")),
            dimensions=[str(value) for value in table.get("dimensions", [])],
            metrics=[str(value) for value in table.get("metrics", [])],
        )
        for table in payload.get("tables", [])
    ]

    join_rules = [
        JoinRule(
            left=str(rule["left"]),
            right=str(rule["right"]),
            keys=[str(value) for value in rule.get("keys", [])],
        )
        for rule in payload.get("joinRules", [])
    ]

    policy_raw = payload.get("policy", {})
    policy = SemanticPolicy(
        restricted_columns=[str(value) for value in policy_raw.get("restrictedColumns", [])],
        default_row_limit=int(policy_raw.get("defaultRowLimit", 1000)),
        max_row_limit=int(policy_raw.get("maxRowLimit", 5000)),
    )

    if not tables:
        raise RuntimeError("Semantic model has no tables defined.")

    return SemanticModel(
        version=str(payload.get("version", "unknown")),
        description=str(payload.get("description", "")),
        tables=tables,
        join_rules=join_rules,
        policy=policy,
    )


def load_semantic_model(path: Optional[str] = None) -> SemanticModel:
    model_path = Path(path).expanduser() if path else _default_model_path()
    if not model_path.exists():
        raise RuntimeError(f"Semantic model not found at {model_path}")

    payload = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Semantic model file is not a JSON object.")
    return _as_semantic_model(payload)


def semantic_model_summary(model: SemanticModel) -> str:
    table_lines = []
    for table in model.tables:
        dimensions = ", ".join(table.dimensions) if table.dimensions else "none"
        metrics = ", ".join(table.metrics) if table.metrics else "none"
        table_lines.append(
            f"- {table.name}: {table.description}\n"
            f"  dimensions: {dimensions}\n"
            f"  metrics: {metrics}"
        )

    join_lines = [
        f"- {rule.left} <-> {rule.right} on ({', '.join(rule.keys)})" for rule in model.join_rules
    ]

    if not join_lines:
        join_lines = ["- no cross-table joins defined; prefer single-table queries"]

    return (
        f"Semantic model version: {model.version}\n"
        f"Description: {model.description}\n"
        "Tables:\n"
        f"{chr(10).join(table_lines)}\n"
        "Join rules:\n"
        f"{chr(10).join(join_lines)}\n"
        "Policy:\n"
        f"- Restricted columns: {', '.join(model.policy.restricted_columns) or 'none'}\n"
        f"- Default row limit: {model.policy.default_row_limit}\n"
        f"- Max row limit: {model.policy.max_row_limit}"
    )


def _short_text(text: str, *, max_chars: int = 140) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 3]}..."


def _collect_business_concepts(model: SemanticModel, *, max_concepts: int = 14) -> list[str]:
    sources: list[str] = [model.description]
    for table in model.tables:
        sources.append(table.description)
        sources.extend(item.replace("_", " ") for item in table.dimensions)
        sources.extend(item.replace("_", " ") for item in table.metrics)
    corpus = " ".join(sources).lower()

    concepts: list[str] = []
    if "spend" in corpus:
        concepts.append("spend")
    if "transaction" in corpus:
        concepts.append("transactions")
    if "channel" in corpus:
        concepts.append("channel mix")
    if "repeat" in corpus or "new " in corpus or "new_" in corpus:
        concepts.append("repeat vs new behavior")
    if any(token in corpus for token in ["state", "city", "location", "store"]):
        concepts.append("geographic breakdowns")
    if "household" in corpus:
        concepts.append("household/store relationships")
    if "consumer" in corpus or "commercial" in corpus:
        concepts.append("consumer vs commercial mix")
    if any(token in corpus for token in ["cnp", "card not present", "card-not-present", "cp_spend", "cp_transactions"]):
        concepts.append("card-present vs card-not-present mix")
    if "mcc" in corpus or "merchant category" in corpus:
        concepts.append("merchant category behavior")

    if not concepts:
        concepts = ["spend", "transactions", "channel mix"]
    return concepts[:max_concepts]


def _collect_time_semantics(model: SemanticModel) -> list[str]:
    found: set[str] = set()
    for table in model.tables:
        for field in [*table.dimensions, *table.metrics]:
            lowered = field.lower()
            if "date" in lowered:
                found.add("date")
                found.update({"day", "week", "month", "quarter", "year"})
            if "time" in lowered:
                found.add("time")
            if "day" in lowered:
                found.add("day")
            if "week" in lowered:
                found.add("week")
            if "month" in lowered:
                found.add("month")
            if "quarter" in lowered:
                found.add("quarter")
            if "year" in lowered:
                found.add("year")
    ordered = ["date", "time", "day", "week", "month", "quarter", "year"]
    return [token for token in ordered if token in found]


def semantic_model_planner_context(
    model: SemanticModel,
    *,
    max_concepts: int = 14,
) -> str:
    concepts = _collect_business_concepts(model, max_concepts=max_concepts)
    time_semantics = _collect_time_semantics(model)
    concept_text = ", ".join(concepts) if concepts else "none"
    time_text = ", ".join(time_semantics) if time_semantics else "none"
    return (
        "Planning scope (minimum context):\n"
        f"- Domain: {_short_text(model.description, max_chars=180)}\n"
        "- Planner responsibility: decide relevance and delegate the minimum independent task set to specialist sub-analysts.\n"
        f"- In-domain business concepts: {concept_text}\n"
        f"- Time semantics: {time_text}\n"
        "- Keep planner tasks free of physical schema details (no table or column names).\n"
        "- Mark as out_of_domain only when the request is clearly unrelated to this business scope."
    )
