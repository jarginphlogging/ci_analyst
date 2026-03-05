from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_ANALYST_MAX_ATTEMPTS = 3
_ANALYST_TIMEOUT_SECONDS = 90.0
_ANALYST_BASE_RETRY_DELAY_SECONDS = 0.3
_ANALYST_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class SandboxCortexHttpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        detail: Any = None,
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.response_text = response_text


def _error_detail_from_response(response: httpx.Response) -> Any:
    detail: Any = response.text
    try:
        body = response.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body.get("detail")
        else:
            detail = body
    except Exception:  # noqa: BLE001
        pass
    return detail


async def execute_sandbox_sql(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.sandbox_cortex_api_key:
        headers["Authorization"] = f"Bearer {settings.sandbox_cortex_api_key}"

    started_at = time.perf_counter()
    logger.info(
        "Sandbox Cortex SQL request started",
        extra={
            "event": "provider.sandbox_sql.request.started",
            "sqlChars": len(sql),
            "sqlPreview": " ".join(sql.split())[:260],
        },
    )
    try:
        async with httpx.AsyncClient(timeout=settings.sandbox_sql_timeout_seconds) as client:
            response = await client.post(
                f"{settings.sandbox_cortex_base_url.rstrip('/')}/query",
                headers=headers,
                json={"sql": sql},
            )
    except Exception:
        logger.exception(
            "Sandbox Cortex SQL request transport failure",
            extra={
                "event": "provider.sandbox_sql.request.failed_transport",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    if response.status_code >= 400:
        detail: Any = response.text
        try:
            body = response.json()
            if isinstance(body, dict) and "detail" in body:
                detail = body.get("detail")
            else:
                detail = body
        except Exception:  # noqa: BLE001
            pass
        logger.error(
            "Sandbox Cortex SQL request returned error",
            extra={
                "event": "provider.sandbox_sql.request.failed_http",
                "statusCode": response.status_code,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "responsePreview": response.text[:500],
            },
        )
        raise SandboxCortexHttpError(
            f"Sandbox Cortex request failed ({response.status_code}).",
            status_code=response.status_code,
            detail=detail,
            response_text=response.text,
        )

    payload: Any = response.json()
    logger.info(
        "Sandbox Cortex SQL request completed",
        extra={
            "event": "provider.sandbox_sql.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return list(payload["rows"])
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return list(payload["data"])
    if isinstance(payload, list):
        return list(payload)

    raise RuntimeError("Sandbox Cortex response did not include a rows/data array.")


async def analyze_message(
    *,
    conversation_id: str,
    message: str,
    history: list[str] | None = None,
    step_id: str | None = None,
    retry_feedback: list[dict[str, Any]] | None = None,
    dependency_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "conversationId": conversation_id,
        "message": message,
        "history": history or [],
        "stepId": step_id,
        "retryFeedback": retry_feedback or [],
        "dependencyContext": dependency_context or [],
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.sandbox_cortex_api_key:
        headers["Authorization"] = f"Bearer {settings.sandbox_cortex_api_key}"

    started_at = time.perf_counter()
    logger.info(
        "Sandbox analyst request started",
        extra={
            "event": "provider.sandbox_analyst.request.started",
            "conversationId": conversation_id,
            "historyDepth": len(history or []),
            "retryFeedbackCount": len(retry_feedback or []),
        },
    )
    response: httpx.Response | None = None
    for attempt in range(1, _ANALYST_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_ANALYST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.sandbox_cortex_base_url.rstrip('/')}/message",
                    headers=headers,
                    json=request_payload,
                )
        except Exception:
            if attempt < _ANALYST_MAX_ATTEMPTS:
                logger.warning(
                    "Sandbox analyst request transport failure; retrying",
                    extra={
                        "event": "provider.sandbox_analyst.request.retry_transport",
                        "attempt": attempt,
                        "maxAttempts": _ANALYST_MAX_ATTEMPTS,
                        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                        "conversationId": conversation_id,
                    },
                )
                await asyncio.sleep(_ANALYST_BASE_RETRY_DELAY_SECONDS * attempt)
                continue
            logger.exception(
                "Sandbox analyst request transport failure",
                extra={
                    "event": "provider.sandbox_analyst.request.failed_transport",
                    "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                    "conversationId": conversation_id,
                    "attempt": attempt,
                },
            )
            raise

        if response.status_code < 400:
            break

        detail = _error_detail_from_response(response)
        retryable_status = response.status_code in _ANALYST_RETRYABLE_STATUS_CODES
        if retryable_status and attempt < _ANALYST_MAX_ATTEMPTS:
            logger.warning(
                "Sandbox analyst request returned transient HTTP error; retrying",
                extra={
                    "event": "provider.sandbox_analyst.request.retry_http",
                    "statusCode": response.status_code,
                    "attempt": attempt,
                    "maxAttempts": _ANALYST_MAX_ATTEMPTS,
                    "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                    "conversationId": conversation_id,
                    "responsePreview": response.text[:500],
                },
            )
            await asyncio.sleep(_ANALYST_BASE_RETRY_DELAY_SECONDS * attempt)
            continue

        logger.error(
            "Sandbox analyst request returned error",
            extra={
                "event": "provider.sandbox_analyst.request.failed_http",
                "statusCode": response.status_code,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "conversationId": conversation_id,
                "responsePreview": response.text[:500],
                "attempt": attempt,
            },
        )
        raise SandboxCortexHttpError(
            f"Sandbox Cortex analyst request failed ({response.status_code}).",
            status_code=response.status_code,
            detail=detail,
            response_text=response.text,
        )

    if response is None:
        raise RuntimeError("Sandbox Cortex analyst request did not receive a response.")

    body: Any = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Sandbox Cortex analyst response was not an object.")
    logger.info(
        "Sandbox analyst request completed",
        extra={
            "event": "provider.sandbox_analyst.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "conversationId": conversation_id,
        },
    )
    return body
