from __future__ import annotations

from typing import Any

import pytest

from app.config import settings
from app.providers import azure_openai


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_azure_chat_completion_compiles_response_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: dict[str, Any] = {}

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
            nonlocal captured_payload
            _ = args
            captured_payload = dict(kwargs.get("json", {}))
            return _FakeResponse(
                status_code=200,
                payload={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
                text='{"choices":[{"message":{"content":"{\\"answer\\":\\"ok\\"}"}}]}',
            )

    original_endpoint = settings.azure_openai_endpoint
    original_key = settings.azure_openai_api_key
    original_deployment = settings.azure_openai_deployment
    try:
        object.__setattr__(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
        object.__setattr__(settings, "azure_openai_api_key", "test-key")
        object.__setattr__(settings, "azure_openai_deployment", "test-deployment")
        monkeypatch.setattr(azure_openai.httpx, "AsyncClient", _FakeAsyncClient)

        result = await azure_openai.chat_completion(
            system_prompt="system",
            user_prompt="user",
            response_schema={
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "default": ""},
                    "confidence": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["answer"],
            },
            response_schema_name="test_payload",
        )
    finally:
        object.__setattr__(settings, "azure_openai_endpoint", original_endpoint)
        object.__setattr__(settings, "azure_openai_api_key", original_key)
        object.__setattr__(settings, "azure_openai_deployment", original_deployment)

    schema = captured_payload["response_format"]["json_schema"]["schema"]
    assert result == '{"answer":"ok"}'
    assert schema["required"] == ["answer", "confidence"]
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["answer"]
