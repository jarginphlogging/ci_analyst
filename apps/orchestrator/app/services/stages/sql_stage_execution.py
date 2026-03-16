from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import SqlExecutionResult
from app.services.stages.sql_stage_models import GeneratedStep, MAX_SQL_ATTEMPTS, SqlGenerationBlockedError
from app.services.stages.sql_state_machine import SqlFailureCode, error_category, informed_clarification_message, normalize_retry_feedback
from app.services.stages.sql_stage_runtime import ProgressFn, emit_progress
from app.services.table_analysis import normalize_rows

SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
logger = logging.getLogger(__name__)


class AllNullRowsError(RuntimeError):
    pass


async def execute_sql(sql: str, *, sql_fn: SqlFn) -> SqlExecutionResult:
    started_at = perf_counter()
    sql_preview = " ".join(sql.split())[:260]
    logger.info(
        "SQL execution started",
        extra={
            "event": "sql.execution.started",
            "sqlChars": len(sql),
            "sqlPreview": sql_preview,
        },
    )
    try:
        raw_rows = await sql_fn(sql)
        normalized_rows = normalize_rows(raw_rows)
    except Exception:
        logger.exception(
            "SQL execution failed",
            extra={
                "event": "sql.execution.failed",
                "sqlChars": len(sql),
                "sqlPreview": sql_preview,
                "durationMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        raise
    logger.info(
        "SQL execution completed",
        extra={
            "event": "sql.execution.completed",
            "durationMs": round((perf_counter() - started_at) * 1000, 2),
            "rowCount": len(normalized_rows),
            "sqlPreview": sql_preview,
        },
    )
    return SqlExecutionResult(sql=sql, rows=normalized_rows, rowCount=len(normalized_rows))


def rows_all_null(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for row in rows:
        if any(value is not None for value in row.values()):
            return False
    return True


async def execute_generated_step(
    *,
    generated: GeneratedStep,
    total_steps: int,
    progress_callback: ProgressFn | None,
    sql_fn: SqlFn,
) -> tuple[int, SqlExecutionResult]:
    await emit_progress(progress_callback, f"Running data retrieval step {generated.index + 1}/{total_steps}")
    if generated.rows is not None and generated.sql:
        normalized_rows = normalize_rows(generated.rows)
        result = SqlExecutionResult(
            sql=generated.sql,
            rows=normalized_rows,
            rowCount=len(normalized_rows),
        )
    else:
        if not generated.sql:
            raise RuntimeError("SQL generation produced no executable SQL.")
        result = await execute_sql(generated.sql, sql_fn=sql_fn)
    if rows_all_null(result.rows):
        raise AllNullRowsError("SQL returned only null values.")
    await emit_progress(
        progress_callback,
        f"Completed data retrieval step {generated.index + 1}/{total_steps} ({result.rowCount} rows)",
    )
    return generated.index, result


def is_timeout_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return True
    return "timeout" in type(error).__name__.lower()


def raise_execution_timeout(
    *,
    generated: GeneratedStep,
    attempt: int,
    retry_feedback: list[dict[str, Any]],
    error_text: str,
    elapsed_seconds: float,
) -> None:
    retry_feedback_tail = normalize_retry_feedback(retry_feedback[-8:], max_items=6)
    user_message = informed_clarification_message(
        step_goal=generated.step.goal,
        clarification_question=generated.clarification_question,
        clarification_kind=generated.clarification_kind,
        retry_feedback=retry_feedback_tail,
        max_attempts=MAX_SQL_ATTEMPTS,
        fallback_error=error_text,
    )
    raise SqlGenerationBlockedError(
        stop_reason="clarification",
        user_message=user_message,
        detail={
            "phase": "sql_execution",
            "stepId": generated.step.id,
            "attempt": attempt,
            "maxAttempts": MAX_SQL_ATTEMPTS,
            "error": error_text,
            "errorCode": SqlFailureCode.EXECUTION_TIMEOUT.value,
            "errorCategory": error_category(SqlFailureCode.EXECUTION_TIMEOUT),
            "failedSql": generated.sql,
            "retryFeedback": retry_feedback_tail,
            "elapsedSeconds": round(elapsed_seconds, 2),
            "slaSeconds": settings.sql_step_sla_seconds,
        },
    )
