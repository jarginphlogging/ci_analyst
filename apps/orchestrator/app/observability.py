from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import settings

_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
_SESSION_ID: ContextVar[str] = ContextVar("session_id", default="-")
_LOGGING_CONFIGURED = False

_BASE_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(item) for item in value]
    return str(value)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = _REQUEST_ID.get()
        record.session_id = _SESSION_ID.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "requestId": getattr(record, "request_id", _REQUEST_ID.get()),
            "sessionId": getattr(record, "session_id", _SESSION_ID.get()),
        }

        event = getattr(record, "event", None)
        if event is not None:
            payload["event"] = _to_json_safe(event)

        for key, value in record.__dict__.items():
            if key in _BASE_RECORD_FIELDS or key.startswith("_"):
                continue
            if key in {"request_id", "session_id", "event"}:
                continue
            if key in payload:
                payload[f"log_{key}"] = _to_json_safe(value)
            else:
                payload[key] = _to_json_safe(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = str(record.stack_info)

        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    stream_handler.addFilter(ContextFilter())
    root_logger.addHandler(stream_handler)
    root_logger.setLevel(level)
    _LOGGING_CONFIGURED = True


def get_request_id() -> str:
    return _REQUEST_ID.get()


@contextmanager
def bind_log_context(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[None]:
    request_token: Token[str] | None = None
    session_token: Token[str] | None = None
    try:
        if request_id is not None:
            request_token = _REQUEST_ID.set(request_id)
        if session_id is not None:
            session_token = _SESSION_ID.set(session_id)
        yield
    finally:
        if session_token is not None:
            _SESSION_ID.reset(session_token)
        if request_token is not None:
            _REQUEST_ID.reset(request_token)
