from __future__ import annotations

from typing import Any

import pytest

from app.config import settings
from app.providers import anthropic_llm


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        text: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_anthropic_chat_completion_retries_transient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[_FakeResponse] = [
        _FakeResponse(status_code=502, payload={"error": "upstream"}, text="bad gateway"),
        _FakeResponse(
            status_code=200,
            payload={"content": [{"type": "text", "text": "ok"}]},
            text='{"content":[{"type":"text","text":"ok"}]}',
        ),
    ]
    post_calls = 0

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            _ = exc_type
            _ = exc
            _ = tb
            return False

        async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            nonlocal post_calls
            _ = args
            _ = kwargs
            post_calls += 1
            return responses.pop(0)

    async def _no_sleep(_: float) -> None:
        return None

    original_key = settings.anthropic_api_key
    original_model = settings.anthropic_model
    try:
        object.__setattr__(settings, "anthropic_api_key", "test-key")
        object.__setattr__(settings, "anthropic_model", "test-model")
        monkeypatch.setattr(anthropic_llm.httpx, "AsyncClient", _FakeAsyncClient)
        monkeypatch.setattr(anthropic_llm.asyncio, "sleep", _no_sleep)

        result = await anthropic_llm.chat_completion(
            system_prompt="system",
            user_prompt="user",
            response_json=False,
        )
    finally:
        object.__setattr__(settings, "anthropic_api_key", original_key)
        object.__setattr__(settings, "anthropic_model", original_model)

    assert post_calls == 2
    assert result == "ok"


@pytest.mark.asyncio
async def test_anthropic_chat_completion_retries_structured_parse_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[_FakeResponse] = [
        _FakeResponse(
            status_code=200,
            payload={"content": [{"type": "text", "text": "not a tool result"}]},
            text='{"content":[{"type":"text"}]}',
        ),
        _FakeResponse(
            status_code=200,
            payload={"content": [{"type": "tool_use", "name": "sql_payload", "input": {"sql": "SELECT 1"}}]},
            text='{"content":[{"type":"tool_use"}]}',
        ),
    ]
    post_calls = 0

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            _ = exc_type
            _ = exc
            _ = tb
            return False

        async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            nonlocal post_calls
            _ = args
            _ = kwargs
            post_calls += 1
            return responses.pop(0)

    async def _no_sleep(_: float) -> None:
        return None

    original_key = settings.anthropic_api_key
    original_model = settings.anthropic_model
    try:
        object.__setattr__(settings, "anthropic_api_key", "test-key")
        object.__setattr__(settings, "anthropic_model", "test-model")
        monkeypatch.setattr(anthropic_llm.httpx, "AsyncClient", _FakeAsyncClient)
        monkeypatch.setattr(anthropic_llm.asyncio, "sleep", _no_sleep)

        result = await anthropic_llm.chat_completion(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
            response_schema_name="sql_payload",
        )
    finally:
        object.__setattr__(settings, "anthropic_api_key", original_key)
        object.__setattr__(settings, "anthropic_model", original_model)

    assert post_calls == 2
    assert "SELECT 1" in result


@pytest.mark.asyncio
async def test_anthropic_chat_completion_uses_retry_after_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[_FakeResponse] = [
        _FakeResponse(
            status_code=429,
            payload={"error": {"type": "rate_limit_error"}},
            text='{"error":{"type":"rate_limit_error"}}',
            headers={"retry-after": "2"},
        ),
        _FakeResponse(
            status_code=200,
            payload={"content": [{"type": "text", "text": "ok"}]},
            text='{"content":[{"type":"text","text":"ok"}]}',
        ),
    ]
    post_calls = 0
    sleep_values: list[float] = []

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            _ = exc_type
            _ = exc
            _ = tb
            return False

        async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            nonlocal post_calls
            _ = args
            _ = kwargs
            post_calls += 1
            return responses.pop(0)

    async def _record_sleep(value: float) -> None:
        sleep_values.append(value)
        return None

    original_key = settings.anthropic_api_key
    original_model = settings.anthropic_model
    try:
        object.__setattr__(settings, "anthropic_api_key", "test-key")
        object.__setattr__(settings, "anthropic_model", "test-model")
        monkeypatch.setattr(anthropic_llm.httpx, "AsyncClient", _FakeAsyncClient)
        monkeypatch.setattr(anthropic_llm.asyncio, "sleep", _record_sleep)

        result = await anthropic_llm.chat_completion(
            system_prompt="system",
            user_prompt="user",
            response_json=False,
        )
    finally:
        object.__setattr__(settings, "anthropic_api_key", original_key)
        object.__setattr__(settings, "anthropic_model", original_model)

    assert post_calls == 2
    assert result == "ok"
    assert sleep_values
    assert sleep_values[0] >= 2.0
