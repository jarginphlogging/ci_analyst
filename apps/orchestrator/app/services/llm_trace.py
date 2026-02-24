from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class LlmTraceEntry:
    stage: str
    provider: str
    system_prompt: str
    user_prompt: str
    max_tokens: int | None
    temperature: float | None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: str | None = None
    parsed_response: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class LlmTraceCollector:
    entries: list[LlmTraceEntry] = field(default_factory=list)

    def record(self, entry: LlmTraceEntry) -> None:
        self.entries.append(entry)


_current_collector: ContextVar[LlmTraceCollector | None] = ContextVar("llm_trace_collector", default=None)
_current_stage: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar("llm_trace_stage", default=None)


@contextmanager
def bind_llm_trace_collector(collector: LlmTraceCollector) -> Iterator[None]:
    token = _current_collector.set(collector)
    try:
        yield
    finally:
        _current_collector.reset(token)


@contextmanager
def llm_trace_stage(stage: str, metadata: dict[str, Any] | None = None) -> Iterator[None]:
    token = _current_stage.set((stage, dict(metadata or {})))
    try:
        yield
    finally:
        _current_stage.reset(token)


def record_llm_trace(
    *,
    provider: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None,
    temperature: float | None,
    raw_response: str | None = None,
    parsed_response: dict[str, Any] | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    collector = _current_collector.get()
    if collector is None:
        return

    stage_info = _current_stage.get()
    stage_name = "unknown_stage"
    stage_metadata: dict[str, Any] = {}
    if stage_info is not None:
        stage_name, stage_metadata = stage_info

    merged_metadata = dict(stage_metadata)
    if metadata:
        merged_metadata.update(metadata)

    collector.record(
        LlmTraceEntry(
            stage=stage_name,
            provider=provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            metadata=merged_metadata,
            raw_response=raw_response,
            parsed_response=parsed_response,
            error=error,
        )
    )
