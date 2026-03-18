from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class SemanticModelSource:
    path: Path
    raw_text: str


def default_semantic_model_source_path() -> Path:
    env_path = settings.semantic_model_path
    if env_path:
        return Path(env_path).expanduser()

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "semantic_model.yaml"
        if candidate.exists():
            return candidate
    raise RuntimeError("Could not locate semantic_model.yaml in repository parents.")


def load_semantic_model_source(path: str | None = None) -> SemanticModelSource:
    model_path = Path(path).expanduser() if path else default_semantic_model_source_path()
    if not model_path.exists():
        raise RuntimeError(f"Semantic model YAML not found at {model_path}")

    raw_text = model_path.read_text(encoding="utf-8")
    return SemanticModelSource(
        path=model_path,
        raw_text=raw_text,
    )
