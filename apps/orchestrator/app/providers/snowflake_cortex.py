from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings


essential_settings_help = (
    "Snowflake Cortex credentials are not configured. Set SNOWFLAKE_CORTEX_BASE_URL "
    "and SNOWFLAKE_CORTEX_API_KEY."
)


async def execute_cortex_sql(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    """Execute SQL via Snowflake Cortex-style REST endpoint.

    This adapter keeps response parsing permissive because API wrappers can return
    different envelopes (`rows`, `data`, or a nested payload).
    """

    if not settings.has_snowflake_credentials():
        raise RuntimeError(essential_settings_help)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.snowflake_cortex_base_url}/query",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.snowflake_cortex_api_key}",
            },
            json={
                "sql": sql,
                "warehouse": settings.snowflake_cortex_warehouse,
                "database": settings.snowflake_cortex_database,
                "schema": settings.snowflake_cortex_schema,
            },
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Snowflake Cortex request failed ({response.status_code}): {response.text}")

    payload: Any = response.json()

    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return list(payload["rows"])
        if isinstance(payload.get("data"), list):
            return list(payload["data"])
        nested = payload.get("result")
        if isinstance(nested, dict) and isinstance(nested.get("rows"), list):
            return list(nested["rows"])

    if isinstance(payload, list):
        return list(payload)

    raise RuntimeError("Snowflake Cortex response did not include a rows/data array.")
