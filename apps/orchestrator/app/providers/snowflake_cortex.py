from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


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

    started_at = time.perf_counter()
    logger.info(
        "Snowflake Cortex SQL request started",
        extra={
            "event": "provider.snowflake_sql.request.started",
            "sqlChars": len(sql),
            "sqlPreview": " ".join(sql.split())[:260],
        },
    )
    try:
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
    except Exception:
        logger.exception(
            "Snowflake Cortex SQL request transport failure",
            extra={
                "event": "provider.snowflake_sql.request.failed_transport",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    if response.status_code >= 400:
        logger.error(
            "Snowflake Cortex SQL request returned error",
            extra={
                "event": "provider.snowflake_sql.request.failed_http",
                "statusCode": response.status_code,
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "responsePreview": response.text[:500],
            },
        )
        raise RuntimeError(f"Snowflake Cortex request failed ({response.status_code}): {response.text}")

    payload: Any = response.json()
    logger.info(
        "Snowflake Cortex SQL request completed",
        extra={
            "event": "provider.snowflake_sql.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )

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
