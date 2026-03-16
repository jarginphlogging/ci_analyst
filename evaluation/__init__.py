from __future__ import annotations

from evaluation.common import load_backend_env

# Keep backend env centralized in apps/orchestrator/.env for all eval entrypoints.
load_backend_env()
