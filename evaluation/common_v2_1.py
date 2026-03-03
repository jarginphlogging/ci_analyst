from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_orchestrator_path() -> Path:
    orchestrator_path = repo_root() / "apps" / "orchestrator"
    if str(orchestrator_path) not in sys.path:
        sys.path.insert(0, str(orchestrator_path))
    return orchestrator_path


def compact(value: Any, *, max_chars: int = 800) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."

