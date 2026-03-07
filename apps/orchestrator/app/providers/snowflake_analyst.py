from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


_ANALYST_HELP = (
    "Snowflake Cortex Analyst credentials are not configured. Set "
    "SNOWFLAKE_CORTEX_BASE_URL, SNOWFLAKE_CORTEX_API_KEY, and one semantic model setting "
    "(SNOWFLAKE_CORTEX_SEMANTIC_MODEL_FILE, SNOWFLAKE_CORTEX_SEMANTIC_MODEL, "
    "SNOWFLAKE_CORTEX_SEMANTIC_VIEW, or SNOWFLAKE_CORTEX_SEMANTIC_MODELS_JSON)."
)


def _semantic_model_payload() -> dict[str, Any]:
    if settings.snowflake_cortex_semantic_models_json:
        try:
            parsed = json.loads(settings.snowflake_cortex_semantic_models_json)
            if isinstance(parsed, list) and parsed:
                return {"semantic_models": parsed}
        except json.JSONDecodeError:
            raise RuntimeError("SNOWFLAKE_CORTEX_SEMANTIC_MODELS_JSON must be valid JSON array text.") from None

    if settings.snowflake_cortex_semantic_model_file:
        return {"semantic_model_file": settings.snowflake_cortex_semantic_model_file}
    if settings.snowflake_cortex_semantic_model:
        return {"semantic_model": settings.snowflake_cortex_semantic_model}
    if settings.snowflake_cortex_semantic_view:
        return {"semantic_view": settings.snowflake_cortex_semantic_view}
    raise RuntimeError(_ANALYST_HELP)


def _compose_messages(*, history: list[str] | None, message: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in (history or [])[-6:]:
        text = str(item).strip()
        if not text:
            continue
        messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            }
        )
    messages.append(
        {
            "role": "user",
            "content": [{"type": "text", "text": message}],
        }
    )
    return messages


def _normalize_analyst_response(*, body: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    content_blocks: list[dict[str, Any]] = []
    message_payload = body.get("message")
    if isinstance(message_payload, dict):
        raw_content = message_payload.get("content")
        if isinstance(raw_content, list):
            content_blocks = [item for item in raw_content if isinstance(item, dict)]

    sql = ""
    text_parts: list[str] = []
    suggestions: list[str] = []

    for block in content_blocks:
        block_type = str(block.get("type", "")).strip().lower()
        if block_type == "sql":
            candidate = str(block.get("statement") or block.get("sql") or "").strip()
            if candidate:
                sql = candidate
        elif block_type == "text":
            text = str(block.get("text", "")).strip()
            if text:
                text_parts.append(text)
        elif block_type in {"suggestions", "suggestion"}:
            raw_suggestions = block.get("suggestions")
            if isinstance(raw_suggestions, list):
                for item in raw_suggestions[:4]:
                    suggestion_text = str(item).strip()
                    if suggestion_text:
                        suggestions.append(suggestion_text)

    response_type = "sql_ready" if sql else "clarification"
    clarification_kind = "none"
    clarification_question = ""
    if response_type != "sql_ready":
        clarification_kind = "user_input_required"
        if suggestions:
            clarification_question = "Which of these interpretations should I use? " + " | ".join(suggestions)
        elif text_parts:
            clarification_question = text_parts[0]
        else:
            raise RuntimeError("Snowflake Cortex Analyst returned neither SQL nor clarification text.")

    request_id = str(body.get("request_id", "")).strip()
    return {
        "type": response_type,
        "conversationId": conversation_id,
        "sql": sql,
        "lightResponse": text_parts[0] if text_parts else "",
        "interpretationNotes": text_parts[:2],
        "caveats": [],
        "clarificationQuestion": clarification_question,
        "clarificationKind": clarification_kind,
        "notRelevantReason": "",
        "assumptions": [],
        "rows": [],
        "rowCount": 0,
        "failedSql": None,
    }


async def analyze_message(
    *,
    conversation_id: str,
    message: str,
    history: list[str] | None = None,
    step_id: str | None = None,
    retry_feedback: list[dict[str, Any]] | None = None,
    dependency_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _ = step_id
    _ = retry_feedback
    _ = dependency_context
    if not settings.has_snowflake_analyst_credentials():
        raise RuntimeError(_ANALYST_HELP)

    payload: dict[str, Any] = {
        "messages": _compose_messages(history=history, message=message),
    }
    payload.update(_semantic_model_payload())

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.snowflake_cortex_api_key}",
    }
    if settings.snowflake_cortex_auth_token_type:
        headers["X-Snowflake-Authorization-Token-Type"] = settings.snowflake_cortex_auth_token_type

    started_at = time.perf_counter()
    logger.info(
        "Snowflake Cortex Analyst request started",
        extra={
            "event": "provider.snowflake_analyst.request.started",
            "conversationId": conversation_id,
            "historyDepth": len(history or []),
        },
    )

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{settings.snowflake_cortex_base_url.rstrip('/')}/message",
                headers=headers,
                json=payload,
            )
    except Exception:
        logger.exception(
            "Snowflake Cortex Analyst request transport failure",
            extra={
                "event": "provider.snowflake_analyst.request.failed_transport",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "conversationId": conversation_id,
            },
        )
        raise

    if response.status_code >= 400:
        logger.error(
            "Snowflake Cortex Analyst request returned error",
            extra={
                "event": "provider.snowflake_analyst.request.failed_http",
                "statusCode": response.status_code,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "conversationId": conversation_id,
                "responsePreview": response.text[:500],
            },
        )
        raise RuntimeError(
            f"Snowflake Cortex Analyst request failed ({response.status_code}): {response.text}"
        )

    body: Any = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Snowflake Cortex Analyst response was not an object.")

    logger.info(
        "Snowflake Cortex Analyst request completed",
        extra={
            "event": "provider.snowflake_analyst.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "conversationId": conversation_id,
        },
    )
    return _normalize_analyst_response(body=body, conversation_id=conversation_id)
