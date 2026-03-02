from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _messages_endpoint() -> str:
    if not settings.has_anthropic_credentials():
        raise RuntimeError(
            "Anthropic credentials are not configured. Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL."
        )
    return f"{settings.anthropic_base_url.rstrip('/')}/v1/messages"


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

    endpoint = _messages_endpoint()
    started_at = time.perf_counter()
    effective_system = system_prompt
    if response_json:
        effective_system = (
            f"{effective_system}\n\n"
            "Return only one strict JSON object. Do not add markdown fences or prose."
        )

    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "system": effective_system,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    schema_tool_name = ""
    if response_schema is not None:
        schema_tool_name = (response_schema_name or "structured_response").strip() or "structured_response"
        payload["tools"] = [
            {
                "name": schema_tool_name,
                "description": "Emit structured response payload.",
                "input_schema": response_schema,
            }
        ]
        payload["tool_choice"] = {"type": "tool", "name": schema_tool_name}

    logger.info(
        "Anthropic request started",
        extra={
            "event": "provider.anthropic.request.started",
            "responseJson": response_json,
            "responseSchema": response_schema is not None,
            "maxTokens": max_tokens,
            "temperature": temperature,
            "systemPromptChars": len(system_prompt),
            "userPromptChars": len(user_prompt),
        },
    )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": str(settings.anthropic_api_key),
                    "anthropic-version": settings.anthropic_api_version,
                },
                json=payload,
            )
    except Exception:
        logger.exception(
            "Anthropic request failed before response",
            extra={
                "event": "provider.anthropic.request.failed_transport",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    if response.status_code >= 400:
        logger.error(
            "Anthropic request returned error",
            extra={
                "event": "provider.anthropic.request.failed_http",
                "statusCode": response.status_code,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "responsePreview": response.text[:500],
            },
        )
        raise RuntimeError(f"Anthropic request failed ({response.status_code}): {response.text}")

    body = response.json()
    content = body.get("content", [])
    if not isinstance(content, list):
        logger.info(
            "Anthropic request completed with non-list content",
            extra={
                "event": "provider.anthropic.request.completed",
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
            raise RuntimeError("Anthropic structured response did not include a valid tool input payload.")
        raise RuntimeError("Anthropic structured response did not include the required tool output.")

    texts = [str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"]
    logger.info(
        "Anthropic request completed",
        extra={
            "event": "provider.anthropic.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "textParts": len(texts),
        },
    )
    return "".join(texts)
