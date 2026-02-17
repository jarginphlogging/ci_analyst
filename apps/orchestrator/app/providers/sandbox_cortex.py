from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings


async def execute_sandbox_sql(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.sandbox_cortex_api_key:
        headers["Authorization"] = f"Bearer {settings.sandbox_cortex_api_key}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.sandbox_cortex_base_url.rstrip('/')}/query",
            headers=headers,
            json={"sql": sql},
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Sandbox Cortex request failed ({response.status_code}): {response.text}")

    payload: Any = response.json()
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
    route: str | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "conversationId": conversation_id,
        "message": message,
        "history": history or [],
        "route": route,
        "stepId": step_id,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.sandbox_cortex_api_key:
        headers["Authorization"] = f"Bearer {settings.sandbox_cortex_api_key}"

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.sandbox_cortex_base_url.rstrip('/')}/message",
            headers=headers,
            json=request_payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Sandbox Cortex analyst request failed ({response.status_code}): {response.text}")

    body: Any = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Sandbox Cortex analyst response was not an object.")
    return body
