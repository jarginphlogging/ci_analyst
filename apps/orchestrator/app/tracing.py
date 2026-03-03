from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

try:
    from opentelemetry import trace
except Exception:  # noqa: BLE001
    class _NoopSpan:
        def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def add_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _NoopSpanManager:
        def __enter__(self) -> _NoopSpan:
            return _NoopSpan()

        def __exit__(self, *_args: Any) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, _span_name: str) -> _NoopSpanManager:
            return _NoopSpanManager()

    class _NoopTraceModule:
        @staticmethod
        def get_tracer(_name: str) -> _NoopTracer:
            return _NoopTracer()

        @staticmethod
        def get_current_span() -> _NoopSpan:
            return _NoopSpan()

    trace = _NoopTraceModule()  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_TRACING_INITIALIZED = False


def _get_tracer():
    # Resolve tracer lazily so post-register providers are honored.
    return trace.get_tracer("ci_analyst.orchestrator")


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return json.dumps({"serialization_error": str(value)}, ensure_ascii=True)


def initialize_tracing(*, project_name: str = "cortex-analyst-pipeline") -> None:
    """Initialize Phoenix/OpenTelemetry once.

    This keeps tracing additive. If Phoenix dependencies are absent or environment
    is not configured, OpenTelemetry no-op behavior remains and runtime continues.
    """

    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        return

    try:
        from phoenix.otel import register

        register(project_name=project_name)
        logger.info(
            "Phoenix tracing registered",
            extra={"event": "tracing.phoenix.registered", "projectName": project_name},
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Phoenix tracing registration skipped",
            extra={
                "event": "tracing.phoenix.skipped",
                "projectName": project_name,
                "reason": str(error),
            },
        )
    finally:
        _TRACING_INITIALIZED = True


@contextmanager
def turn_span(
    *,
    session_id: str,
    mode: str,
    message: str,
    history_depth: int,
) -> Iterator[None]:
    with _get_tracer().start_as_current_span("pipeline.turn") as span:
        span.set_attribute("session.id", session_id)
        span.set_attribute("turn.mode", mode)
        span.set_attribute("history.depth", history_depth)
        span.set_attribute("input.message", _compact_json({"message": message}))
        yield


@contextmanager
def stage_span(
    *,
    span_name: str,
    stage_id: str,
    input_value: Any,
    attributes: dict[str, Any] | None = None,
) -> Iterator[None]:
    with _get_tracer().start_as_current_span(span_name) as span:
        span.set_attribute("eval.stage", stage_id)
        span.set_attribute("input.value", _compact_json(input_value))
        for key, value in (attributes or {}).items():
            if value is None:
                continue
            span.set_attribute(key, value if isinstance(value, (bool, int, float, str)) else _compact_json(value))
        yield


def set_stage_output(output_value: Any, *, attributes: dict[str, Any] | None = None) -> None:
    span = trace.get_current_span()
    if span is None:
        return
    span.set_attribute("output.value", _compact_json(output_value))
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        span.set_attribute(key, value if isinstance(value, (bool, int, float, str)) else _compact_json(value))


def add_check_event(*, name: str, passed: bool, reason: str) -> None:
    span = trace.get_current_span()
    if span is None:
        return
    span.add_event(
        "eval.inline_check",
        {
            "eval.check.name": name,
            "eval.check.passed": passed,
            "eval.check.reason": reason,
        },
    )
