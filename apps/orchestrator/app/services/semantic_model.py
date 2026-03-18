from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.services.semantic_model_source import load_semantic_model_source


@dataclass(frozen=True)
class SemanticTable:
    name: str
    description: str
    dimensions: list[str]
    metrics: list[str]


@dataclass(frozen=True)
class SemanticModel:
    name: str
    description: str
    tables: list[SemanticTable]


def _default_model_path() -> Path:
    env_path = settings.semantic_model_path
    if env_path:
        return Path(env_path).expanduser()

    return load_semantic_model_source().path


def _named_fields(items: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(items, list):
        return names
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


def _as_semantic_model(payload: dict[str, Any]) -> SemanticModel:
    tables: list[SemanticTable] = []
    raw_tables = payload.get("tables", [])
    if isinstance(raw_tables, list):
        for table in raw_tables:
            if not isinstance(table, dict):
                continue
            dimensions = _named_fields(table.get("dimensions"))
            time_dimensions = _named_fields(table.get("time_dimensions"))
            combined_dimensions = dimensions[:]
            for field in time_dimensions:
                if field not in combined_dimensions:
                    combined_dimensions.append(field)
            tables.append(
                SemanticTable(
                    name=str(table.get("name", "")).strip(),
                    description=str(table.get("description", "")).strip(),
                    dimensions=combined_dimensions,
                    metrics=_named_fields(table.get("measures")),
                )
            )
    tables = [table for table in tables if table.name]

    if not tables:
        raise RuntimeError("Semantic model has no tables defined.")

    return SemanticModel(
        name=str(payload.get("name", "unknown")).strip() or "unknown",
        description=str(payload.get("description", "")).strip(),
        tables=tables,
    )


def load_semantic_model(path: str | None = None) -> SemanticModel:
    model_path = Path(path).expanduser() if path else _default_model_path()
    if not model_path.exists():
        raise RuntimeError(f"Semantic model not found at {model_path}")

    payload = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Semantic model file is not a YAML object.")
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

    return (
        f"Semantic model name: {model.name}\n"
        f"Description: {model.description}\n"
        "Tables:\n"
        f"{chr(10).join(table_lines)}"
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
