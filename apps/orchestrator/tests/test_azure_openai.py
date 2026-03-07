from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import settings
from app.providers import azure_openai


class _FakePart:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, content: Any) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: Any) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: Any) -> None:
        self.choices = [_FakeChoice(content)]


@pytest.mark.asyncio
async def test_azure_chat_completion_compiles_response_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_client_kwargs: dict[str, Any] = {}
    captured_payload: dict[str, Any] = {}

    class _FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal captured_client_kwargs
            captured_client_kwargs = dict(kwargs)
            self.chat = self
            self.completions = self

        async def create(self, **kwargs: Any) -> _FakeResponse:
            nonlocal captured_payload
            captured_payload = dict(kwargs)
            return _FakeResponse('{"answer":"ok"}')

        async def close(self) -> None:
            return None

    original_endpoint = settings.azure_openai_endpoint
    original_key = settings.azure_openai_api_key
    original_deployment = settings.azure_openai_deployment
    original_gateway_key = settings.azure_openai_gateway_api_key
    original_gateway_header = settings.azure_openai_gateway_api_key_header
    original_auth_mode = settings.azure_openai_auth_mode
    try:
        object.__setattr__(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
        object.__setattr__(settings, "azure_openai_api_key", "test-key")
        object.__setattr__(settings, "azure_openai_deployment", "test-deployment")
        object.__setattr__(settings, "azure_openai_gateway_api_key", "gateway-key")
        object.__setattr__(settings, "azure_openai_gateway_api_key_header", "Api-Key")
        object.__setattr__(settings, "azure_openai_auth_mode", "api_key")
        monkeypatch.setattr(azure_openai, "AsyncAzureOpenAI", _FakeAsyncAzureOpenAI)

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
        object.__setattr__(settings, "azure_openai_gateway_api_key", original_gateway_key)
        object.__setattr__(settings, "azure_openai_gateway_api_key_header", original_gateway_header)
        object.__setattr__(settings, "azure_openai_auth_mode", original_auth_mode)

    schema = captured_payload["response_format"]["json_schema"]["schema"]
    assert result == '{"answer":"ok"}'
    assert captured_client_kwargs["api_key"] == "test-key"
    assert captured_client_kwargs["default_headers"] == {"Api-Key": "gateway-key"}
    assert captured_payload["model"] == "test-deployment"
    assert schema["required"] == ["answer", "confidence"]
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["answer"]


@pytest.mark.asyncio
async def test_azure_chat_completion_uses_certificate_token_for_client_auth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_client_kwargs: dict[str, Any] = {}
    cert_file = tmp_path / "work-cert.pem"
    cert_file.write_text("test-cert", encoding="utf-8")

    class _FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal captured_client_kwargs
            captured_client_kwargs = dict(kwargs)
            self.chat = self
            self.completions = self

        async def create(self, **kwargs: Any) -> _FakeResponse:
            _ = kwargs
            return _FakeResponse([_FakePart("hello "), _FakePart("world")])

        async def close(self) -> None:
            return None

    class _FakeAccessToken:
        token = "aad-token"
        expires_on = 4102444800

    class _FakeCertificateCredential:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["tenant_id"] == "tenant-id"
            assert kwargs["client_id"] == "client-id"
            assert kwargs["certificate_data"] == b"test-cert"
            assert kwargs["password"] == "cert-password"

        def get_token(self, scope: str) -> _FakeAccessToken:
            assert scope == settings.azure_openai_scope
            return _FakeAccessToken()

    original_endpoint = settings.azure_openai_endpoint
    original_deployment = settings.azure_openai_deployment
    original_auth_mode = settings.azure_openai_auth_mode
    original_tenant = settings.azure_tenant_id
    original_client_id = settings.azure_spn_client_id
    original_cert_path = settings.azure_spn_cert_path
    original_cert_password = settings.azure_spn_cert_password
    original_gateway_key = settings.azure_openai_gateway_api_key
    try:
        azure_openai._TOKEN_CACHE["token"] = None
        azure_openai._TOKEN_CACHE["expires_on"] = 0
        object.__setattr__(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
        object.__setattr__(settings, "azure_openai_deployment", "gpt-4")
        object.__setattr__(settings, "azure_openai_auth_mode", "certificate")
        object.__setattr__(settings, "azure_tenant_id", "tenant-id")
        object.__setattr__(settings, "azure_spn_client_id", "client-id")
        object.__setattr__(settings, "azure_spn_cert_path", str(cert_file))
        object.__setattr__(settings, "azure_spn_cert_password", "cert-password")
        object.__setattr__(settings, "azure_openai_gateway_api_key", "gateway-key")
        monkeypatch.setattr(azure_openai, "AsyncAzureOpenAI", _FakeAsyncAzureOpenAI)
        monkeypatch.setitem(__import__("sys").modules, "azure.identity", type("M", (), {"CertificateCredential": _FakeCertificateCredential})())

        result = await azure_openai.chat_completion(system_prompt="system", user_prompt="user")
    finally:
        object.__setattr__(settings, "azure_openai_endpoint", original_endpoint)
        object.__setattr__(settings, "azure_openai_deployment", original_deployment)
        object.__setattr__(settings, "azure_openai_auth_mode", original_auth_mode)
        object.__setattr__(settings, "azure_tenant_id", original_tenant)
        object.__setattr__(settings, "azure_spn_client_id", original_client_id)
        object.__setattr__(settings, "azure_spn_cert_path", original_cert_path)
        object.__setattr__(settings, "azure_spn_cert_password", original_cert_password)
        object.__setattr__(settings, "azure_openai_gateway_api_key", original_gateway_key)
        azure_openai._TOKEN_CACHE["token"] = None
        azure_openai._TOKEN_CACHE["expires_on"] = 0

    assert result == "hello world"
    assert captured_client_kwargs["api_key"] == "aad-token"
    assert captured_client_kwargs["default_headers"] == {"Api-Key": "gateway-key"}
