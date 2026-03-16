from __future__ import annotations

import io
import json
import sys
from typing import Any

import pytest

from app.config import settings
from app.providers import anthropic_bedrock


class _FakeBoto3Module:
    def client(self, service_name: str) -> object:
        assert service_name == "sts"
        return object()


class _FakeCdaoModule:
    def __init__(self, response_payload: dict[str, Any]) -> None:
        self.response_payload = response_payload
        self.calls: list[dict[str, Any]] = []

    def bedrock_byoa_invoke_model(self, data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"data": dict(data), "payload": dict(payload)})
        return {"body": io.BytesIO(json.dumps(self.response_payload).encode("utf-8"))}


@pytest.mark.asyncio
async def test_anthropic_bedrock_chat_completion_uses_enterprise_invoke_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cdao = _FakeCdaoModule({"content": [{"type": "text", "text": "ok"}]})

    original_llm_provider = settings.llm_provider_raw
    original_account = settings.anthropic_bedrock_aws_account_number
    original_region = settings.anthropic_bedrock_aws_region
    original_workspace_id = settings.anthropic_bedrock_workspace_id
    original_execution_role = settings.anthropic_bedrock_is_execution_role
    original_model_id = settings.anthropic_bedrock_model_id
    original_model_name = settings.anthropic_bedrock_model_name
    try:
        object.__setattr__(settings, "llm_provider_raw", "anthropic_bedrock")
        object.__setattr__(settings, "anthropic_bedrock_aws_account_number", "146431566378")
        object.__setattr__(settings, "anthropic_bedrock_aws_region", "us-east-1")
        object.__setattr__(settings, "anthropic_bedrock_workspace_id", "904579")
        object.__setattr__(settings, "anthropic_bedrock_is_execution_role", False)
        object.__setattr__(
            settings,
            "anthropic_bedrock_model_id",
            "arn:aws:bedrock:us-east-1:146431566378:application-inference-profile/test-profile",
        )
        object.__setattr__(settings, "anthropic_bedrock_model_name", "anthropic.claude-opus-4-1")
        monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module())
        monkeypatch.setitem(sys.modules, "cdao", fake_cdao)

        result = await anthropic_bedrock.chat_completion(
            system_prompt="system",
            user_prompt="what is 3+2?",
            temperature=0.1,
            max_tokens=2048,
        )
    finally:
        object.__setattr__(settings, "llm_provider_raw", original_llm_provider)
        object.__setattr__(settings, "anthropic_bedrock_aws_account_number", original_account)
        object.__setattr__(settings, "anthropic_bedrock_aws_region", original_region)
        object.__setattr__(settings, "anthropic_bedrock_workspace_id", original_workspace_id)
        object.__setattr__(settings, "anthropic_bedrock_is_execution_role", original_execution_role)
        object.__setattr__(settings, "anthropic_bedrock_model_id", original_model_id)
        object.__setattr__(settings, "anthropic_bedrock_model_name", original_model_name)

    assert result == "ok"
    assert len(fake_cdao.calls) == 1
    call = fake_cdao.calls[0]
    assert call["data"] == {
        "AWSAccountNumber": "146431566378",
        "AWSRegion": "us-east-1",
        "WorkspaceID": "904579",
        "isExecutionRole": False,
    }
    assert call["payload"]["modelId"] == "arn:aws:bedrock:us-east-1:146431566378:application-inference-profile/test-profile"

    body = json.loads(call["payload"]["body"])
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["system"] == "system"
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 2048
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "what is 3+2?"}]}]


@pytest.mark.asyncio
async def test_anthropic_bedrock_chat_completion_returns_structured_tool_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cdao = _FakeCdaoModule(
        {"content": [{"type": "tool_use", "name": "sql_payload", "input": {"sql": "SELECT 1"}}]}
    )

    original_llm_provider = settings.llm_provider_raw
    original_account = settings.anthropic_bedrock_aws_account_number
    original_region = settings.anthropic_bedrock_aws_region
    original_workspace_id = settings.anthropic_bedrock_workspace_id
    original_model_id = settings.anthropic_bedrock_model_id
    try:
        object.__setattr__(settings, "llm_provider_raw", "anthropic_bedrock")
        object.__setattr__(settings, "anthropic_bedrock_aws_account_number", "146431566378")
        object.__setattr__(settings, "anthropic_bedrock_aws_region", "us-east-1")
        object.__setattr__(settings, "anthropic_bedrock_workspace_id", "904579")
        object.__setattr__(
            settings,
            "anthropic_bedrock_model_id",
            "arn:aws:bedrock:us-east-1:146431566378:application-inference-profile/test-profile",
        )
        monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module())
        monkeypatch.setitem(sys.modules, "cdao", fake_cdao)

        result = await anthropic_bedrock.chat_completion(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
            response_schema_name="sql_payload",
        )
    finally:
        object.__setattr__(settings, "llm_provider_raw", original_llm_provider)
        object.__setattr__(settings, "anthropic_bedrock_aws_account_number", original_account)
        object.__setattr__(settings, "anthropic_bedrock_aws_region", original_region)
        object.__setattr__(settings, "anthropic_bedrock_workspace_id", original_workspace_id)
        object.__setattr__(settings, "anthropic_bedrock_model_id", original_model_id)

    assert json.loads(result) == {"sql": "SELECT 1"}
    call = fake_cdao.calls[0]
    body = json.loads(call["payload"]["body"])
    assert body["tool_choice"] == {"type": "tool", "name": "sql_payload"}
    assert body["tools"][0]["name"] == "sql_payload"
