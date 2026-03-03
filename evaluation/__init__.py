from __future__ import annotations

from evaluation.common_v2_1 import load_backend_env

# Keep backend env centralized in apps/orchestrator/.env for all eval entrypoints.
load_backend_env()
