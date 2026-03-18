from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_ANTHROPIC_TIMEOUT_SECONDS = 45.0
_ANTHROPIC_MAX_ATTEMPTS = 4
_ANTHROPIC_BASE_RETRY_DELAY_SECONDS = 0.35
_ANTHROPIC_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_ANTHROPIC_MAX_RETRY_DELAY_SECONDS = 30.0


def _messages_endpoint() -> str:
    if not settings.has_anthropic_credentials():
        raise RuntimeError(
            "Anthropic credentials are not configured. Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL."
        )
    return f"{settings.anthropic_base_url.rstrip('/')}/v1/messages"


def _parse_retry_seconds(response: httpx.Response, *, attempt: int) -> float:
    retry_after_header = str(response.headers.get("retry-after", "")).strip()
    retry_after_seconds = 0.0
    if retry_after_header:
        try:
            retry_after_seconds = max(0.0, float(retry_after_header))
        except ValueError:
            retry_after_seconds = 0.0

    input_reset_header = str(response.headers.get("anthropic-ratelimit-input-tokens-reset", "")).strip()
    reset_wait_seconds = 0.0
    if input_reset_header:
        try:
            parsed = datetime.fromisoformat(input_reset_header.replace("Z", "+00:00"))
            reset_wait_seconds = max(0.0, parsed.astimezone(timezone.utc).timestamp() - time.time())
        except ValueError:
            reset_wait_seconds = 0.0

    fallback_seconds = _ANTHROPIC_BASE_RETRY_DELAY_SECONDS * attempt
    return min(_ANTHROPIC_MAX_RETRY_DELAY_SECONDS, max(fallback_seconds, retry_after_seconds, reset_wait_seconds))


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
) -> str:
    endpoint = _messages_endpoint()
    started_at = time.perf_counter()

    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "system": system_prompt,
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
            "responseSchema": response_schema is not None,
            "maxTokens": max_tokens,
            "temperature": temperature,
            "systemPromptChars": len(system_prompt),
            "userPromptChars": len(user_prompt),
        },
    )
    for attempt in range(1, _ANTHROPIC_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_ANTHROPIC_TIMEOUT_SECONDS) as client:
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
            if attempt < _ANTHROPIC_MAX_ATTEMPTS:
                logger.warning(
                    "Anthropic request transport failure; retrying",
                    extra={
                        "event": "provider.anthropic.request.retry_transport",
                        "attempt": attempt,
                        "maxAttempts": _ANTHROPIC_MAX_ATTEMPTS,
                        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                )
                await asyncio.sleep(_ANTHROPIC_BASE_RETRY_DELAY_SECONDS * attempt)
                continue
            logger.exception(
                "Anthropic request failed before response",
                extra={
                    "event": "provider.anthropic.request.failed_transport",
                    "attempt": attempt,
                    "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        if response.status_code >= 400:
            if response.status_code in _ANTHROPIC_RETRYABLE_STATUS_CODES and attempt < _ANTHROPIC_MAX_ATTEMPTS:
                wait_seconds = _parse_retry_seconds(response, attempt=attempt)
                logger.warning(
                    "Anthropic request returned transient HTTP error; retrying",
                    extra={
                        "event": "provider.anthropic.request.retry_http",
                        "statusCode": response.status_code,
                        "attempt": attempt,
                        "maxAttempts": _ANTHROPIC_MAX_ATTEMPTS,
                        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                        "retryDelaySeconds": round(wait_seconds, 2),
                        "responsePreview": response.text[:500],
                    },
                )
                await asyncio.sleep(wait_seconds)
                continue
            logger.error(
                "Anthropic request returned error",
                extra={
                    "event": "provider.anthropic.request.failed_http",
                    "statusCode": response.status_code,
                    "attempt": attempt,
                    "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                    "responsePreview": response.text[:500],
                },
            )
            raise RuntimeError(f"Anthropic request failed ({response.status_code}): {response.text}")

        try:
            body = response.json()
            content = body.get("content", [])
            if not isinstance(content, list):
                logger.info(
                    "Anthropic request completed with non-list content",
                    extra={
                        "event": "provider.anthropic.request.completed",
                        "attempt": attempt,
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
                    "attempt": attempt,
                    "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                    "textParts": len(texts),
                },
            )
            return "".join(texts)
        except Exception as error:
            retryable_parse = response_schema is not None
            if retryable_parse and attempt < _ANTHROPIC_MAX_ATTEMPTS:
                logger.warning(
                    "Anthropic structured response parse failed; retrying",
                    extra={
                        "event": "provider.anthropic.request.retry_parse",
                        "attempt": attempt,
                        "maxAttempts": _ANTHROPIC_MAX_ATTEMPTS,
                        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                        "error": str(error),
                    },
                )
                await asyncio.sleep(_ANTHROPIC_BASE_RETRY_DELAY_SECONDS * attempt)
                continue
            raise

    raise RuntimeError("Anthropic request exhausted retries without a valid response.")
