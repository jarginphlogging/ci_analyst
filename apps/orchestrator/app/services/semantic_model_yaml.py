from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_STOPWORDS = {
    "about",
    "across",
    "all",
    "also",
    "always",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "context",
    "customer",
    "customers",
    "data",
    "date",
    "dates",
    "description",
    "for",
    "from",
    "group",
    "if",
    "in",
    "insights",
    "is",
    "it",
    "latest",
    "level",
    "model",
    "month",
    "name",
    "of",
    "on",
    "or",
    "period",
    "query",
    "show",
    "table",
    "that",
    "the",
    "this",
    "through",
    "to",
    "use",
    "when",
    "with",
    "year",
}


@dataclass(frozen=True)
class SemanticModelYaml:
    path: Path
    raw_text: str
    domain_terms: tuple[str, ...]
    domain_phrases: tuple[str, ...]


def _default_yaml_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "semantic_model.yaml"
        if candidate.exists():
            return candidate
    raise RuntimeError("Could not locate semantic_model.yaml in repository parents.")


def _normalize_token(token: str) -> str:
    return token.strip().lower().replace("-", "_")


def _tokenize(text: str) -> list[str]:
    return [_normalize_token(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)]


def _parse_yaml_terms(raw_text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    name_matches = re.findall(r"^\s*-\s*name:\s*([A-Za-z0-9_]+)\s*$", raw_text, flags=re.MULTILINE)
    table_matches = re.findall(r"^\s*-\s*name:\s*(cia_[a-z0-9_]+)\s*$", raw_text, flags=re.MULTILINE)

    phrase_candidates: set[str] = set()
    token_candidates: set[str] = set()

    for name in [*name_matches, *table_matches, "customer insights"]:
        cleaned = name.strip().lower().replace("-", "_")
        if cleaned:
            phrase_candidates.add(cleaned)
            phrase_candidates.add(cleaned.replace("_", " "))
            for token in cleaned.split("_"):
                if len(token) >= 3 and token not in _STOPWORDS:
                    token_candidates.add(token)

    for token in _tokenize(raw_text):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        token_candidates.add(token)

    domain_terms = tuple(sorted(token_candidates))
    domain_phrases = tuple(sorted(phrase_candidates))
    return domain_terms, domain_phrases


def load_semantic_model_yaml(path: str | None = None) -> SemanticModelYaml:
    model_path = Path(path).expanduser() if path else _default_yaml_path()
    if not model_path.exists():
        raise RuntimeError(f"Semantic model YAML not found at {model_path}")

    raw_text = model_path.read_text(encoding="utf-8")
    domain_terms, domain_phrases = _parse_yaml_terms(raw_text)
    return SemanticModelYaml(
        path=model_path,
        raw_text=raw_text,
        domain_terms=domain_terms,
        domain_phrases=domain_phrases,
    )


def semantic_model_yaml_prompt_context(model: SemanticModelYaml, *, max_named_fields: int = 80) -> str:
    field_names = re.findall(r"^\s*-\s*name:\s*([A-Za-z0-9_]+)\s*$", model.raw_text, flags=re.MULTILINE)
    unique_fields: list[str] = []
    seen: set[str] = set()
    for field in field_names:
        lowered = field.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_fields.append(field)
        if len(unique_fields) >= max_named_fields:
            break

    header_excerpt = "\n".join(model.raw_text.splitlines()[:70])
    return (
        f"Semantic model source: {model.path}\n"
        f"Named fields and entities (subset): {', '.join(unique_fields) or 'none'}\n\n"
        "Semantic model excerpt:\n"
        f"{header_excerpt}"
    )
