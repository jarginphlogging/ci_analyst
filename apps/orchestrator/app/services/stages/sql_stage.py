from __future__ import annotations

import asyncio
import inspect
import logging
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import QueryPlanStep, SqlExecutionResult
from app.services.semantic_model import SemanticModel
from app.services.stages.sql_stage_generation import SqlStepGenerator
from app.services.stages.sql_stage_models import (
    MAX_SQL_ATTEMPTS,
    OUT_OF_DOMAIN_MESSAGE,
    GeneratedStep,
    SqlGenerationBlockedError,
)
from app.services.stages.sql_state_machine import (
    SqlFailureCode,
    build_retry_event,
    error_category,
    failure_code_for_generated,
    informed_clarification_message,
    normalize_retry_feedback,
)
from app.services.stages.sql_stage_topology import dependency_levels, execution_dispatch
from app.services.table_analysis import normalize_rows

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
ProgressFn = Callable[[str], Optional[Awaitable[None]]]
logger = logging.getLogger(__name__)


class _AllNullRowsError(RuntimeError):
    pass


async def _emit_progress(progress_callback: ProgressFn | None, message: str) -> None:
    if progress_callback is None:
        return
    maybe_result = progress_callback(message)
    if inspect.isawaitable(maybe_result):
        await maybe_result


class SqlExecutionStage:
    def __init__(
        self,
        *,
        model: SemanticModel,
        ask_llm_json: AskLlmJsonFn,
        sql_fn: SqlFn,
        analyst_fn: AnalystFn | None = None,
    ) -> None:
        self._sql_fn = sql_fn
        self._analyst_fn = analyst_fn
        self._latest_retry_feedback: list[dict[str, Any]] = []
        self._generator = SqlStepGenerator(
            model=model,
            ask_llm_json=ask_llm_json,
            analyst_fn=analyst_fn,
        )

    @property
    def latest_retry_feedback(self) -> list[dict[str, Any]]:
        return list(self._latest_retry_feedback)

    @staticmethod
    def _flatten_retry_feedback(retry_feedback_by_step: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for step_id, entries in retry_feedback_by_step.items():
            for entry in entries[-6:]:
                payload = dict(entry)
                payload.setdefault("stepId", step_id)
                flattened.append(payload)
        return normalize_retry_feedback(flattened, max_items=12)

    async def _execute_sql(self, sql: str) -> SqlExecutionResult:
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
            raw_rows = await self._sql_fn(sql)
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
        return SqlExecutionResult(
            sql=sql,
            rows=normalized_rows,
            rowCount=len(normalized_rows),
        )

    @staticmethod
    def _informed_clarification_message(
        generated: GeneratedStep,
        *,
        retry_feedback: list[dict[str, Any]],
        fallback_error: str = "",
    ) -> str:
        return informed_clarification_message(
            step_goal=generated.step.goal,
            clarification_question=generated.clarification_question,
            clarification_kind=generated.clarification_kind,
            retry_feedback=retry_feedback,
            max_attempts=MAX_SQL_ATTEMPTS,
            fallback_error=fallback_error,
        )

    @staticmethod
    def _blocked_from_generated(
        generated: GeneratedStep,
        *,
        attempt: int,
        retry_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationBlockedError:
        failed_sql = generated.attempted_sql or generated.sql
        retry_tail = normalize_retry_feedback((retry_feedback or [])[-6:], max_items=6)
        code = failure_code_for_generated(generated)
        if generated.status == "not_relevant" or code == SqlFailureCode.NOT_RELEVANT:
            return SqlGenerationBlockedError(
                stop_reason="not_relevant",
                user_message=generated.not_relevant_reason or OUT_OF_DOMAIN_MESSAGE,
                detail={
                    "phase": "sql_generation",
                    "stepId": generated.step.id,
                    "attempt": attempt,
                    "provider": generated.provider,
                    "errorCode": SqlFailureCode.NOT_RELEVANT.value,
                    "errorCategory": error_category(SqlFailureCode.NOT_RELEVANT),
                    "reason": generated.not_relevant_reason,
                    "assumptions": generated.assumptions,
                    "failedSql": failed_sql,
                    "retryFeedback": retry_tail,
                },
            )

        generation_detail = generated.generation_error_detail or {}
        if code == SqlFailureCode.USER_INPUT_REQUIRED:
            message = SqlExecutionStage._informed_clarification_message(
                generated,
                retry_feedback=retry_tail,
                fallback_error="",
            )
        else:
            message = f"SQL generation failed ({code.value})."
        return SqlGenerationBlockedError(
            stop_reason="clarification",
            user_message=message,
            detail={
                "phase": "sql_generation",
                "stepId": generated.step.id,
                "attempt": attempt,
                "provider": generated.provider,
                "rationale": generated.rationale,
                "error": generated.clarification_question or generated.rationale,
                "errorCode": code.value,
                "errorCategory": error_category(code),
                "clarificationKind": generated.clarification_kind,
                "assumptions": generated.assumptions,
                "failedSql": failed_sql,
                "retryFeedback": retry_tail,
                "generationErrorDetail": generated.generation_error_detail or {},
            },
        )

    async def _execute_generated_step(
        self,
        *,
        generated: GeneratedStep,
        total_steps: int,
        progress_callback: ProgressFn | None,
    ) -> tuple[int, SqlExecutionResult]:
        def _rows_all_null(rows: list[dict[str, Any]]) -> bool:
            if not rows:
                return False
            for row in rows:
                if any(value is not None for value in row.values()):
                    return False
            return True

        await _emit_progress(progress_callback, f"Running SQL step {generated.index + 1}/{total_steps}")
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
            result = await self._execute_sql(generated.sql)
        if _rows_all_null(result.rows):
            raise _AllNullRowsError("SQL returned only null values.")
        await _emit_progress(
            progress_callback,
            f"Completed SQL step {generated.index + 1}/{total_steps} ({result.rowCount} rows)",
        )
        return generated.index, result

    async def _generate_ready_step(
        self,
        *,
        index: int,
        step: QueryPlanStep,
        total_steps: int,
        message: str,
        route: str,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        retry_feedback_by_step: dict[str, list[dict[str, Any]]],
        assumptions: list[str],
        progress_callback: ProgressFn | None,
        sync_retry_feedback: Callable[[], None],
        start_attempt: int = 1,
    ) -> tuple[GeneratedStep, int]:
        step_retry_feedback = retry_feedback_by_step.setdefault(step.id, [])
        attempt = max(1, start_attempt)
        if attempt == 1:
            await _emit_progress(progress_callback, f"Preparing SQL step {index + 1}/{total_steps}: {step.goal}")
            if self._analyst_fn is not None:
                await _emit_progress(
                    progress_callback,
                    f"Generating SQL for step {index + 1}/{total_steps}",
                )
            else:
                await _emit_progress(progress_callback, f"Drafting governed SQL for step {index + 1}/{total_steps}")
        else:
            await _emit_progress(
                progress_callback,
                f"Regenerating SQL for step {index + 1}/{total_steps} (attempt {attempt}/{MAX_SQL_ATTEMPTS})",
            )

        generated = await self._generator.generate(
            index=index,
            message=message,
            route=route,
            step=step,
            history=history,
            prior_sql=prior_sql,
            conversation_id=conversation_id,
            attempt_number=attempt,
            retry_feedback=step_retry_feedback,
        )
        assumptions.extend(generated.assumptions[:4])
        if generated.rationale:
            assumptions.append(f"{generated.step.id} rationale: {generated.rationale}")

        if generated.status == "sql_ready" and generated.sql:
            return generated, attempt

        sync_retry_feedback()
        raise self._blocked_from_generated(
            generated,
            attempt=attempt,
            retry_feedback=step_retry_feedback,
        )

    async def _execute_with_retries(
        self,
        *,
        generated: GeneratedStep,
        generated_attempt: int,
        total_steps: int,
        message: str,
        route: str,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        retry_feedback_by_step: dict[str, list[dict[str, Any]]],
        assumptions: list[str],
        progress_callback: ProgressFn | None,
        sync_retry_feedback: Callable[[], None],
    ) -> tuple[int, SqlExecutionResult]:
        current_generated = generated
        attempt_cursor = generated_attempt
        step_retry_feedback = retry_feedback_by_step.setdefault(current_generated.step.id, [])

        while True:
            try:
                return await self._execute_generated_step(
                    generated=current_generated,
                    total_steps=total_steps,
                    progress_callback=progress_callback,
                )
            except Exception as error:
                logger.exception(
                    "SQL step execution attempt failed",
                    extra={
                        "event": "sql.execution.retry_failed",
                        "stepId": current_generated.step.id,
                        "attempt": attempt_cursor,
                        "maxAttempts": MAX_SQL_ATTEMPTS,
                        "provider": current_generated.provider,
                        "sqlPreview": " ".join((current_generated.sql or "").split())[:260],
                    },
                )
                error_text = str(error).strip()
                failure_code = (
                    SqlFailureCode.EXECUTION_ALL_NULL_ROWS
                    if isinstance(error, _AllNullRowsError)
                    else SqlFailureCode.EXECUTION_WAREHOUSE_ERROR
                )
                step_retry_feedback.append(
                    build_retry_event(
                        code=failure_code,
                        step_id=current_generated.step.id,
                        attempt=attempt_cursor,
                        provider=current_generated.provider,
                        error=error_text,
                        failed_sql=current_generated.sql,
                        clarification_question=current_generated.clarification_question,
                        clarification_kind=current_generated.clarification_kind,
                    )
                )
                sync_retry_feedback()
                assumptions.append(
                    f"SQL execution retry {attempt_cursor} failed for {current_generated.step.id}: {error}"
                )

                if attempt_cursor >= MAX_SQL_ATTEMPTS:
                    retry_feedback_tail = normalize_retry_feedback(step_retry_feedback[-8:], max_items=6)
                    user_message = informed_clarification_message(
                        step_goal=current_generated.step.goal,
                        clarification_question=current_generated.clarification_question,
                        clarification_kind=current_generated.clarification_kind,
                        retry_feedback=retry_feedback_tail,
                        max_attempts=MAX_SQL_ATTEMPTS,
                        fallback_error=error_text,
                    )
                    raise SqlGenerationBlockedError(
                        stop_reason="clarification",
                        user_message=user_message,
                        detail={
                            "phase": "sql_execution",
                            "stepId": current_generated.step.id,
                            "attempt": attempt_cursor,
                            "maxAttempts": MAX_SQL_ATTEMPTS,
                            "error": error_text,
                            "errorCode": SqlFailureCode.RETRY_LIMIT_EXHAUSTED.value,
                            "errorCategory": error_category(failure_code),
                            "failedSql": current_generated.sql,
                            "retryFeedback": retry_feedback_tail,
                        },
                    ) from error

                await _emit_progress(
                    progress_callback,
                    (
                        f"SQL step {current_generated.index + 1}/{total_steps} failed on attempt {attempt_cursor}: "
                        f"{error}. Regenerating and retrying."
                    ),
                )
                retry_history = [
                    *history,
                    f"Previous SQL execution failed for {current_generated.step.id}: {error}",
                    f"Previous SQL:\n{current_generated.sql or ''}",
                ]
                try:
                    current_generated, attempt_cursor = await self._generate_ready_step(
                        index=current_generated.index,
                        step=current_generated.step,
                        total_steps=total_steps,
                        message=message,
                        route=route,
                        history=retry_history,
                        prior_sql=prior_sql,
                        conversation_id=conversation_id,
                        retry_feedback_by_step=retry_feedback_by_step,
                        assumptions=assumptions,
                        progress_callback=progress_callback,
                        sync_retry_feedback=sync_retry_feedback,
                        start_attempt=attempt_cursor + 1,
                    )
                except SqlGenerationBlockedError as blocked:
                    retry_feedback_tail = normalize_retry_feedback(step_retry_feedback[-8:], max_items=6)
                    blocked_detail = blocked.detail if isinstance(blocked.detail, dict) else {}
                    merged_feedback = normalize_retry_feedback(
                        [*retry_feedback_tail, *(blocked_detail.get("retryFeedback") or [])], max_items=6
                    )
                    merged_detail = dict(blocked_detail)
                    merged_detail["retryFeedback"] = merged_feedback
                    raise SqlGenerationBlockedError(
                        stop_reason=blocked.stop_reason,
                        user_message=blocked.user_message,
                        detail=merged_detail,
                    ) from blocked

    async def run_sql(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep],
        history: list[str],
        conversation_id: str = "anonymous",
        progress_callback: ProgressFn | None = None,
    ) -> tuple[list[SqlExecutionResult], list[str]]:
        started_at = perf_counter()
        self._latest_retry_feedback = []
        total_steps = len(plan)
        logger.info(
            "SQL stage started",
            extra={
                "event": "sql.stage.started",
                "stepCount": total_steps,
                "conversationId": conversation_id,
                "parallelLimit": max(1, settings.real_max_parallel_queries),
            },
        )
        try:
            if total_steps == 0:
                return [], []
            plan_limit = max(1, settings.plan_max_steps)
            if total_steps > plan_limit:
                detail = (
                    f"The request expanded to {total_steps} SQL steps, "
                    f"which exceeds the governed limit of {plan_limit} steps per turn."
                )
                raise SqlGenerationBlockedError(
                    stop_reason="clarification",
                    user_message=detail,
                    detail={
                        "phase": "sql_generation",
                        "errorCode": SqlFailureCode.TOO_COMPLEX.value,
                        "errorCategory": error_category(SqlFailureCode.TOO_COMPLEX),
                        "error": detail,
                        "retryFeedback": [],
                    },
                )

            dispatch = execution_dispatch(self._analyst_fn)
            await _emit_progress(
                progress_callback,
                f"Dispatching {total_steps} SQL step(s) to {dispatch.target_label}",
            )
            levels = dependency_levels(plan)
            generation_semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))
            execution_semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))

            prior_sql: list[str] = []
            assumptions: list[str] = []
            generated_by_index: dict[int, GeneratedStep] = {}
            generated_attempt_by_index: dict[int, int] = {}
            retry_feedback_by_step: dict[str, list[dict[str, Any]]] = {}

            def _sync_retry_feedback() -> None:
                self._latest_retry_feedback = self._flatten_retry_feedback(retry_feedback_by_step)

            # Phase 1: generate executable SQL for every plan step (respecting
            # dependency levels so independent steps can run in parallel).
            for level in levels:
                snapshot_prior_sql = list(prior_sql)

                async def _generate(index: int) -> tuple[GeneratedStep, int]:
                    async with generation_semaphore:
                        step = plan[index]
                        return await self._generate_ready_step(
                            index=index,
                            step=step,
                            total_steps=total_steps,
                            message=message,
                            route=route,
                            history=history,
                            prior_sql=snapshot_prior_sql,
                            conversation_id=conversation_id,
                            retry_feedback_by_step=retry_feedback_by_step,
                            assumptions=assumptions,
                            progress_callback=progress_callback,
                            sync_retry_feedback=_sync_retry_feedback,
                        )

                generated_level = (
                    await asyncio.gather(*(_generate(index) for index in level))
                    if len(level) > 1
                    else [await _generate(level[0])]
                )

                for generated, generated_attempt in sorted(generated_level, key=lambda item: item[0].index):
                    prior_sql.append(generated.sql)
                    generated_by_index[generated.index] = generated
                    generated_attempt_by_index[generated.index] = generated_attempt

            generated_steps = [generated_by_index[index] for index in range(total_steps)]
            results_by_index: dict[int, SqlExecutionResult] = {}

            # Phase 2: execute generated SQL, and if warehouse execution fails,
            # regenerate with failure feedback until retry budget is exhausted.
            for level in levels:
                generated_level = [generated_steps[index] for index in level]
                should_parallel_execute = len(generated_level) > 1 and dispatch.parallel_capable
                level_positions = ", ".join(str(index + 1) for index in level)
                await _emit_progress(
                    progress_callback,
                    (
                        f"Executing level [{level_positions}] in parallel on {dispatch.target_label}"
                        if should_parallel_execute
                        else f"Executing level [{level_positions}] serially on {dispatch.target_label}"
                    ),
                )

                async def _execute(generated: GeneratedStep) -> tuple[int, SqlExecutionResult]:
                    async with execution_semaphore:
                        return await self._execute_with_retries(
                            generated=generated,
                            generated_attempt=generated_attempt_by_index.get(generated.index, 1),
                            total_steps=total_steps,
                            message=message,
                            route=route,
                            history=history,
                            prior_sql=prior_sql,
                            conversation_id=conversation_id,
                            retry_feedback_by_step=retry_feedback_by_step,
                            assumptions=assumptions,
                            progress_callback=progress_callback,
                            sync_retry_feedback=_sync_retry_feedback,
                        )

                level_results = (
                    await asyncio.gather(*(_execute(generated) for generated in generated_level))
                    if should_parallel_execute
                    else [await _execute(generated) for generated in generated_level]
                )
                for index, result in level_results:
                    results_by_index[index] = result

            results = [results_by_index[index] for index in range(total_steps)]

            deduped_assumptions: list[str] = []
            for item in assumptions:
                if item not in deduped_assumptions:
                    deduped_assumptions.append(item)
            _sync_retry_feedback()
            logger.info(
                "SQL stage completed",
                extra={
                    "event": "sql.stage.completed",
                    "stepCount": total_steps,
                    "queryCount": len(results),
                    "totalRows": sum(result.rowCount for result in results),
                    "retryFeedbackCount": len(self._latest_retry_feedback),
                    "durationMs": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            return results, deduped_assumptions[:8]
        except Exception:
            logger.exception(
                "SQL stage failed",
                extra={
                    "event": "sql.stage.failed",
                    "stepCount": total_steps,
                    "conversationId": conversation_id,
                    "durationMs": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
