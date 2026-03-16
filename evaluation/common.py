from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    load_dotenv = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def backend_env_path() -> Path:
    return repo_root() / "apps" / "orchestrator" / ".env"


def load_backend_env() -> Path:
    env_path = backend_env_path()
    if load_dotenv and env_path.exists():
        # Match orchestrator semantics: do not overwrite already-exported vars.
        load_dotenv(env_path, override=False)
    return env_path


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
