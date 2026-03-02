from __future__ import annotations

import asyncio
import inspect
import logging
import re
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import QueryPlanStep, SqlExecutionResult
from app.services.semantic_model import SemanticModel
from app.services.stages.sql_stage_generation import SqlStepGenerator
from app.services.stages.sql_stage_models import (
    MAX_SQL_ATTEMPTS,
    OUT_OF_DOMAIN_MESSAGE,
    TOO_COMPLEX_MESSAGE,
    GeneratedStep,
    SqlGenerationBlockedError,
)
from app.services.stages.sql_stage_topology import dependency_levels, execution_dispatch
from app.services.table_analysis import normalize_rows

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
ProgressFn = Callable[[str], Optional[Awaitable[None]]]
logger = logging.getLogger(__name__)
_ASSUMPTION_ATTEMPT_PATTERN = re.compile(r"attempt\s+(\d+)", re.IGNORECASE)


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
        seen: set[str] = set()
        for step_id, entries in retry_feedback_by_step.items():
            for entry in entries[-6:]:
                payload = dict(entry)
                payload.setdefault("stepId", step_id)
                key = str(payload)
                if key in seen:
                    continue
                seen.add(key)
                flattened.append(payload)
        return flattened[:12]

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
    def _derived_retry_feedback_from_assumptions(
        generated: GeneratedStep,
        *,
        attempt: int,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        default_failed_sql = generated.attempted_sql or generated.sql
        for item in generated.assumptions:
            text = str(item).strip()
            if not text:
                continue
            lowered = text.lower()
            if "attempt" not in lowered or "failed" not in lowered:
                continue
            phase = "sql_generation"
            if "sql execution attempt" in lowered:
                phase = "sql_execution"
            elif "sql generation attempt" not in lowered:
                continue

            error_text = text
            if "failed:" in text:
                error_text = text.split("failed:", 1)[1].strip() or text
            attempt_match = _ASSUMPTION_ATTEMPT_PATTERN.search(text)
            entry_attempt = int(attempt_match.group(1)) if attempt_match else attempt
            entries.append(
                {
                    "phase": phase,
                    "stepId": generated.step.id,
                    "attempt": entry_attempt,
                    "provider": generated.provider,
                    "error": error_text,
                    "failedSql": default_failed_sql,
                }
            )

        if entries:
            return entries[:6]

        question = (generated.clarification_question or "").strip()
        lowered_question = question.lower()
        technical_markers = (
            "unbalanced json",
            "timeout",
            "timed out",
            "readtimeout",
            "connection",
            "transport",
            "parse",
            "validation error",
            "failed",
        )
        if question and any(marker in lowered_question for marker in technical_markers):
            return [
                {
                    "phase": "sql_generation",
                    "stepId": generated.step.id,
                    "attempt": attempt,
                    "provider": generated.provider,
                    "error": question,
                    "failedSql": default_failed_sql,
                }
            ]
        return []

    @staticmethod
    def _blocked_from_generated(
        generated: GeneratedStep,
        *,
        attempt: int,
        retry_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationBlockedError:
        failed_sql = generated.attempted_sql or generated.sql
        retry_tail = (retry_feedback or [])[-4:]
        derived_retry_feedback = SqlExecutionStage._derived_retry_feedback_from_assumptions(
            generated,
            attempt=attempt,
        )
        combined_retry_feedback: list[dict[str, Any]] = []
        seen_feedback: set[str] = set()
        for item in [*retry_tail, *derived_retry_feedback]:
            if not isinstance(item, dict):
                continue
            key = str(item)
            if key in seen_feedback:
                continue
            seen_feedback.add(key)
            combined_retry_feedback.append(item)
        retry_payload = combined_retry_feedback[:6]
        if generated.status == "not_relevant":
            return SqlGenerationBlockedError(
                stop_reason="not_relevant",
                user_message=OUT_OF_DOMAIN_MESSAGE,
                detail={
                    "phase": "sql_generation",
                    "stepId": generated.step.id,
                    "attempt": attempt,
                    "provider": generated.provider,
                    "reason": generated.not_relevant_reason,
                    "assumptions": generated.assumptions,
                    "failedSql": failed_sql,
                    "retryFeedback": retry_payload,
                },
            )

        message = generated.clarification_question or generated.rationale or f"SQL generation blocked for {generated.step.id}."
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
                "assumptions": generated.assumptions,
                "failedSql": failed_sql,
                "retryFeedback": retry_payload,
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
            raise RuntimeError("SQL returned only null values; retrying with regenerated SQL.")
        await _emit_progress(
            progress_callback,
            f"Completed SQL step {generated.index + 1}/{total_steps} ({result.rowCount} rows)",
        )
        return generated.index, result

    @staticmethod
    def _should_retry_blocked_generation(generated: GeneratedStep) -> bool:
        if generated.status != "clarification":
            return False
        if any("retry limit reached" in item.lower() for item in generated.assumptions):
            return False
        if generated.attempted_sql and generated.attempted_sql.strip():
            return True
        if any("sql execution attempt" in item.lower() and "failed" in item.lower() for item in generated.assumptions):
            return True
        if any("sql generation attempt" in item.lower() and "failed" in item.lower() for item in generated.assumptions):
            return True
        if any("sql generation failed" in item.lower() for item in generated.assumptions):
            return True
        lowered_question = generated.clarification_question.lower()
        return any(
            token in lowered_question
            for token in (
                "timeout",
                "timed out",
                "readtimeout",
                "connection",
                "transport",
                "unbalanced json",
                "parse",
                "validation error",
                "failed",
                "no executable sql",
            )
        )

    @staticmethod
    def _generation_feedback_entry(generated: GeneratedStep, *, attempt: int) -> dict[str, Any]:
        return {
            "phase": "sql_generation_blocked",
            "stepId": generated.step.id,
            "attempt": attempt,
            "provider": generated.provider,
            "error": generated.clarification_question or generated.not_relevant_reason or "SQL generation did not return executable SQL.",
            "failedSql": generated.attempted_sql or generated.sql,
            "clarificationQuestion": generated.clarification_question,
            "notRelevantReason": generated.not_relevant_reason,
        }

    @staticmethod
    def _generation_retry_history(
        *,
        history: list[str],
        generated: GeneratedStep,
    ) -> list[str]:
        error_text = generated.clarification_question or generated.not_relevant_reason
        return [
            *history,
            f"Previous SQL generation was blocked for {generated.step.id}.",
            f"Previous generator feedback: {error_text or generated.status}",
            f"Previous failed SQL:\n{generated.attempted_sql or generated.sql or ''}",
        ]

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
        execution_recovery: bool = False,
    ) -> tuple[GeneratedStep, int]:
        # This helper centralizes generation retries so policy stays simple:
        # retry only when generator reports a technical/repairable failure.
        step_retry_feedback = retry_feedback_by_step.setdefault(step.id, [])
        attempt_history = list(history)

        for attempt in range(start_attempt, MAX_SQL_ATTEMPTS + 1):
            if attempt == 1:
                await _emit_progress(progress_callback, f"Preparing SQL step {index + 1}/{total_steps}: {step.goal}")
                if self._analyst_fn is not None:
                    await _emit_progress(
                        progress_callback,
                        f"Generating SQL with Snowflake Cortex Analyst for step {index + 1}/{total_steps}",
                    )
                else:
                    await _emit_progress(progress_callback, f"Drafting governed SQL for step {index + 1}/{total_steps}")
            else:
                await _emit_progress(
                    progress_callback,
                    f"Retrying SQL generation for step {index + 1}/{total_steps} (attempt {attempt}/{MAX_SQL_ATTEMPTS})",
                )

            generated = await self._generator.generate(
                index=index,
                message=message,
                route=route,
                step=step,
                history=attempt_history,
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

            # If the status is non-retryable or budget is exhausted, stop early
            # and return a precise blocked error instead of adding more branches.
            can_retry = self._should_retry_blocked_generation(generated) and attempt < MAX_SQL_ATTEMPTS
            if execution_recovery and generated.status == "clarification" and attempt < MAX_SQL_ATTEMPTS:
                # Execution-origin failures should continue retrying technical
                # recovery even if generator replies with a clarification.
                can_retry = True
            if not can_retry:
                sync_retry_feedback()
                raise self._blocked_from_generated(
                    generated,
                    attempt=attempt,
                    retry_feedback=step_retry_feedback,
                )

            step_retry_feedback.append(self._generation_feedback_entry(generated, attempt=attempt))
            sync_retry_feedback()
            assumptions.append(
                f"SQL generation retry {attempt} triggered for {generated.step.id} after blocked attempt."
            )
            attempt_history = self._generation_retry_history(history=attempt_history, generated=generated)

        sync_retry_feedback()
        raise self._blocked_from_generated(
            GeneratedStep(
                index=index,
                step=step,
                provider="llm",
                status="clarification",
                sql=None,
                rationale="",
                assumptions=[],
                clarification_question="SQL generation retry limit reached.",
                not_relevant_reason="",
            ),
            attempt=MAX_SQL_ATTEMPTS,
            retry_feedback=retry_feedback_by_step.get(step.id, []),
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
                step_retry_feedback.append(
                    {
                        "phase": "sql_execution",
                        "stepId": current_generated.step.id,
                        "attempt": attempt_cursor,
                        "provider": current_generated.provider,
                        "error": str(error),
                        "failedSql": current_generated.sql,
                    }
                )
                sync_retry_feedback()
                assumptions.append(
                    f"SQL execution retry {attempt_cursor} failed for {current_generated.step.id}: {error}"
                )

                if attempt_cursor >= MAX_SQL_ATTEMPTS:
                    retry_feedback_tail = step_retry_feedback[-6:]
                    user_message = (
                        str(error).strip()
                        or current_generated.clarification_question
                        or "SQL execution failed after retry limit."
                    )
                    raise SqlGenerationBlockedError(
                        stop_reason="clarification",
                        user_message=user_message,
                        detail={
                            "phase": "sql_execution",
                            "stepId": current_generated.step.id,
                            "attempt": attempt_cursor,
                            "maxAttempts": MAX_SQL_ATTEMPTS,
                            "error": str(error),
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
                        execution_recovery=True,
                    )
                except SqlGenerationBlockedError as blocked:
                    # This branch started from warehouse execution failure, so
                    # surface the terminal condition as an execution failure.
                    retry_feedback_tail = step_retry_feedback[-6:]
                    raise SqlGenerationBlockedError(
                        stop_reason="clarification",
                        user_message=blocked.user_message or str(error),
                        detail={
                            "phase": "sql_execution",
                            "stepId": current_generated.step.id,
                            "attempt": min(MAX_SQL_ATTEMPTS, attempt_cursor + 1),
                            "maxAttempts": MAX_SQL_ATTEMPTS,
                            # Preserve the triggering warehouse error for
                            # operator debugging, even if generation produced
                            # additional clarification/technical notes.
                            "error": str(error) or blocked.detail.get("error"),
                            "failedSql": current_generated.sql,
                            "retryFeedback": retry_feedback_tail,
                            "generationFailure": blocked.detail,
                        },
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
            if total_steps > 5:
                raise SqlGenerationBlockedError(
                    stop_reason="clarification",
                    user_message=TOO_COMPLEX_MESSAGE,
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
