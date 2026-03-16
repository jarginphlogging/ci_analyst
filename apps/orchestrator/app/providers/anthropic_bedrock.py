from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def _require_bedrock_settings() -> None:
    if settings.llm_provider != "anthropic_bedrock":
        raise RuntimeError("Anthropic Bedrock provider is not selected.")
    if not settings.has_anthropic_bedrock_credentials():
        raise RuntimeError(
            "Anthropic Bedrock credentials are not configured. Set "
            "ANTHROPIC_BEDROCK_AWS_ACCOUNT_NUMBER, ANTHROPIC_BEDROCK_AWS_REGION, "
            "ANTHROPIC_BEDROCK_WORKSPACE_ID, and ANTHROPIC_BEDROCK_MODEL_ID."
        )


def _invoke_bedrock_sync(payload: dict[str, Any]) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError("boto3 is required for LLM_PROVIDER=anthropic_bedrock.") from exc

    try:
        import cdao
    except ImportError as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError(
            "The enterprise cdao package is required for LLM_PROVIDER=anthropic_bedrock."
        ) from exc

    # Match the enterprise invocation pattern so Bedrock auth is resolved through the internal package path.
    _ = boto3.client("sts")

    data = {
        "AWSAccountNumber": str(settings.anthropic_bedrock_aws_account_number),
        "AWSRegion": str(settings.anthropic_bedrock_aws_region),
        "WorkspaceID": str(settings.anthropic_bedrock_workspace_id),
        "isExecutionRole": settings.anthropic_bedrock_is_execution_role,
    }
    return cdao.bedrock_byoa_invoke_model(data, payload)


def _parse_response_body(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError("Anthropic Bedrock returned a non-dict response payload.")
    body_stream = response.get("body")
    if body_stream is None:
        raise RuntimeError("Anthropic Bedrock response did not include a body stream.")
    raw = body_stream.read() if hasattr(body_stream, "read") else body_stream
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(str(raw))


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    response_json: bool = False,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
) -> str:
    if response_json and response_schema is not None:
        raise RuntimeError("response_json and response_schema cannot be combined.")

    _require_bedrock_settings()
    started_at = time.perf_counter()
    effective_system = system_prompt
    if response_json:
        effective_system = (
            f"{effective_system}\n\n"
            "Return only one strict JSON object. Do not add markdown fences or prose."
        )

    body: dict[str, Any] = {
        "anthropic_version": settings.anthropic_bedrock_anthropic_version,
        "system": effective_system,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    schema_tool_name = ""
    if response_schema is not None:
        schema_tool_name = (response_schema_name or "structured_response").strip() or "structured_response"
        body["tools"] = [
            {
                "name": schema_tool_name,
                "description": "Emit structured response payload.",
                "input_schema": response_schema,
            }
        ]
        body["tool_choice"] = {"type": "tool", "name": schema_tool_name}

    payload = {
        "modelId": str(settings.anthropic_bedrock_model_id),
        "body": json.dumps(body),
    }

    logger.info(
        "Anthropic Bedrock request started",
        extra={
            "event": "provider.anthropic_bedrock.request.started",
            "modelName": settings.anthropic_bedrock_model_name,
            "responseJson": response_json,
            "responseSchema": response_schema is not None,
            "maxTokens": max_tokens,
            "temperature": temperature,
            "systemPromptChars": len(system_prompt),
            "userPromptChars": len(user_prompt),
        },
    )

    try:
        response = await asyncio.to_thread(_invoke_bedrock_sync, payload)
    except Exception:
        logger.exception(
            "Anthropic Bedrock request failed before response",
            extra={
                "event": "provider.anthropic_bedrock.request.failed_transport",
                "modelName": settings.anthropic_bedrock_model_name,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    parsed = _parse_response_body(response)
    content = parsed.get("content", [])
    if not isinstance(content, list):
        logger.info(
            "Anthropic Bedrock request completed with non-list content",
            extra={
                "event": "provider.anthropic_bedrock.request.completed",
                "modelName": settings.anthropic_bedrock_model_name,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return ""

    if response_schema is not None:
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "tool_use":
                continue
            if schema_tool_name and str(part.get("name", "")) != schema_tool_name:
                continue
            structured = part.get("input")
            if isinstance(structured, dict):
                return json.dumps(structured, ensure_ascii=True)
            if isinstance(structured, str):
                return structured
            raise RuntimeError("Anthropic Bedrock structured response did not include a valid tool input payload.")
        raise RuntimeError("Anthropic Bedrock structured response did not include the required tool output.")

    texts = [str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"]
    logger.info(
        "Anthropic Bedrock request completed",
        extra={
            "event": "provider.anthropic_bedrock.request.completed",
            "modelName": settings.anthropic_bedrock_model_name,
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "textParts": len(texts),
        },
    )
    return "".join(texts)
