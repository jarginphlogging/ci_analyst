from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Optional

from app.services.stages.sql_state_machine import normalize_retry_feedback

ProgressFn = Callable[[str], Optional[Awaitable[None]]]


def append_unique(target: list[str], items: list[str], *, limit: int | None = None) -> None:
    for item in items:
        text = " ".join(str(item).split()).strip()
        if not text or text in target:
            continue
        target.append(text)
        if limit is not None and len(target) >= limit:
            return


async def emit_progress(progress_callback: ProgressFn | None, message: str) -> None:
    if progress_callback is None:
        return
    maybe_result = progress_callback(message)
    if inspect.isawaitable(maybe_result):
        await maybe_result


def flatten_retry_feedback(retry_feedback_by_step: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for step_id, entries in retry_feedback_by_step.items():
        for entry in entries[-6:]:
            payload = dict(entry)
            payload.setdefault("stepId", step_id)
            flattened.append(payload)
    return normalize_retry_feedback(flattened, max_items=12)
