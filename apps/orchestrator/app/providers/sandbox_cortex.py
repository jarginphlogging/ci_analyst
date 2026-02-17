from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings


async def execute_sandbox_sql(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.sandbox_cortex_base_url.rstrip('/')}/query",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.sandbox_cortex_api_key}",
            },
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
