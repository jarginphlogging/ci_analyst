from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.providers import sandbox_cortex
from app.providers.sandbox_cortex import SandboxCortexHttpError


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any, text: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


@pytest.mark.asyncio
async def test_analyze_message_retries_transient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[Any] = [
        _FakeResponse(502, {"detail": {"code": "provider_error", "message": "upstream timeout"}}, "bad gateway"),
        _FakeResponse(200, {"type": "sql_ready", "sql": "SELECT 1", "assumptions": []}, '{"type":"sql_ready"}'),
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

        async def post(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal post_calls
            _ = args
            _ = kwargs
            post_calls += 1
            return queued.pop(0)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sandbox_cortex.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    payload = await sandbox_cortex.analyze_message(
        conversation_id="conv-1",
        message="show total spend",
    )

    assert post_calls == 2
    assert payload["type"] == "sql_ready"
    assert payload["sql"] == "SELECT 1"


@pytest.mark.asyncio
async def test_analyze_message_does_not_retry_non_retryable_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
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

        async def post(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal post_calls
            _ = args
            _ = kwargs
            post_calls += 1
            return _FakeResponse(400, {"detail": {"code": "bad_request"}}, "bad request")

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sandbox_cortex.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    with pytest.raises(SandboxCortexHttpError) as error:
        await sandbox_cortex.analyze_message(
            conversation_id="conv-2",
            message="bad query",
        )

    assert post_calls == 1
    assert error.value.status_code == 400
