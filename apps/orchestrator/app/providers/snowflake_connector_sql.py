from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

from app.config import settings

logger = logging.getLogger(__name__)


_CONNECTOR_HELP = (
    "Snowflake connector credentials are not configured. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
    "and one auth option (SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_FILE)."
)


def _connection_params() -> dict[str, Any]:
    if not settings.has_snowflake_connector_credentials():
        raise RuntimeError(_CONNECTOR_HELP)

    params: dict[str, Any] = {
        "account": settings.snowflake_account,
        "user": settings.snowflake_user,
    }
    if settings.snowflake_password:
        params["password"] = settings.snowflake_password
    if settings.snowflake_private_key_file:
        params["private_key_file"] = settings.snowflake_private_key_file
        if settings.snowflake_private_key_file_pwd:
            params["private_key_file_pwd"] = settings.snowflake_private_key_file_pwd
    if settings.snowflake_authenticator:
        params["authenticator"] = settings.snowflake_authenticator
    if settings.snowflake_role:
        params["role"] = settings.snowflake_role
    if settings.snowflake_warehouse:
        params["warehouse"] = settings.snowflake_warehouse
    if settings.snowflake_database:
        params["database"] = settings.snowflake_database
    if settings.snowflake_schema:
        params["schema"] = settings.snowflake_schema
    return params


def _execute_sync(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    try:
        import snowflake.connector
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "snowflake-connector-python is required for prod SQL execution. "
            "Install orchestrator requirements before running prod mode."
        ) from error

    params = _connection_params()
    connection = snowflake.connector.connect(**params)
    try:
        with connection.cursor(snowflake.connector.DictCursor) as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            normalized: List[Dict[str, Optional[Union[str, int, float, bool]]]] = []
            for row in rows:
                normalized.append(dict(row))
            return normalized
    finally:
        connection.close()


async def execute_snowflake_sql(sql: str) -> List[Dict[str, Optional[Union[str, int, float, bool]]]]:
    started_at = time.perf_counter()
    logger.info(
        "Snowflake connector SQL request started",
        extra={
            "event": "provider.snowflake_connector_sql.request.started",
            "sqlChars": len(sql),
            "sqlPreview": " ".join(sql.split())[:260],
        },
    )
    try:
        rows = await asyncio.to_thread(_execute_sync, sql)
    except Exception:
        logger.exception(
            "Snowflake connector SQL request failed",
            extra={
                "event": "provider.snowflake_connector_sql.request.failed",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    logger.info(
        "Snowflake connector SQL request completed",
        extra={
            "event": "provider.snowflake_connector_sql.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "rowCount": len(rows),
        },
    )
    return rows
