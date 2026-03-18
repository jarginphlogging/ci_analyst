from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import QueryPlanStep, SqlExecutionResult, TemporalScope
from app.services.semantic_model import SemanticModel
from app.services.semantic_policy import SemanticPolicy, load_semantic_policy
from app.services.stages.sql_stage_generation import SqlStepGenerator
from app.services.stages.sql_stage_models import (
    MAX_SQL_ATTEMPTS,
    OUT_OF_DOMAIN_MESSAGE,
    GeneratedStep,
    SqlStageOutcome,
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
from app.services.stages.sql_stage_topology import dependency_indices, dependency_levels, execution_dispatch
from app.services.stages.sql_stage_dependency_context import (
    compact_context_value,
    dependency_context_for_step,
    sample_dependency_rows,
)
from app.services.stages.sql_stage_execution import (
    AllNullRowsError,
    execute_generated_step,
    execute_sql,
    is_timeout_error,
    raise_execution_timeout,
)
from app.services.stages.sql_stage_runtime import append_unique, emit_progress, flatten_retry_feedback
from app.services.stages.sql_stage_temporal import TemporalScopeMismatchError, validate_temporal_scope_result

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
ProgressFn = Callable[[str], Optional[Awaitable[None]]]
logger = logging.getLogger(__name__)


class SqlExecutionStage:
    _DEPENDENCY_CONTEXT_MAX_ROWS = 24
    _DEPENDENCY_CONTEXT_MAX_COLUMNS = 12
    _DEPENDENCY_CONTEXT_MAX_CELL_CHARS = 80

    def __init__(
        self,
        *,
        model: SemanticModel,
        policy: SemanticPolicy | None = None,
        ask_llm_json: AskLlmJsonFn,
        sql_fn: SqlFn,
        analyst_fn: AnalystFn | None = None,
    ) -> None:
        self._sql_fn = sql_fn
        self._analyst_fn = analyst_fn
        self._latest_retry_feedback: list[dict[str, Any]] = []
        resolved_policy = policy or load_semantic_policy()
        self._generator = SqlStepGenerator(
            policy=resolved_policy,
            ask_llm_json=ask_llm_json,
            analyst_fn=analyst_fn,
        )

    @property
    def latest_retry_feedback(self) -> list[dict[str, Any]]:
        return list(self._latest_retry_feedback)

    @staticmethod
    def _flatten_retry_feedback(retry_feedback_by_step: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return flatten_retry_feedback(retry_feedback_by_step)

    @classmethod
    def _compact_context_value(cls, value: Any) -> Any:
        return compact_context_value(
            value,
            max_cell_chars=cls._DEPENDENCY_CONTEXT_MAX_CELL_CHARS,
        )

    @classmethod
    def _sample_dependency_rows(cls, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        return sample_dependency_rows(
            rows,
            max_rows=cls._DEPENDENCY_CONTEXT_MAX_ROWS,
            max_columns=cls._DEPENDENCY_CONTEXT_MAX_COLUMNS,
            max_cell_chars=cls._DEPENDENCY_CONTEXT_MAX_CELL_CHARS,
        )

    @classmethod
    def _dependency_context_for_step(
        cls,
        *,
        index: int,
        dependencies_by_index: dict[int, set[int]],
        plan: list[QueryPlanStep],
        results_by_index: dict[int, SqlExecutionResult],
    ) -> list[dict[str, Any]]:
        return dependency_context_for_step(
            index=index,
            dependencies_by_index=dependencies_by_index,
            plan=plan,
            results_by_index=results_by_index,
            max_rows=cls._DEPENDENCY_CONTEXT_MAX_ROWS,
            max_columns=cls._DEPENDENCY_CONTEXT_MAX_COLUMNS,
            max_cell_chars=cls._DEPENDENCY_CONTEXT_MAX_CELL_CHARS,
        )

    async def _execute_sql(self, sql: str) -> SqlExecutionResult:
        return await execute_sql(sql, sql_fn=self._sql_fn)

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
                    "interpretationNotes": generated.interpretation_notes,
                    "caveats": generated.caveats,
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
                "interpretationNotes": generated.interpretation_notes,
                "caveats": generated.caveats,
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
        return await execute_generated_step(
            generated=generated,
            total_steps=total_steps,
            progress_callback=progress_callback,
            sql_fn=self._sql_fn,
        )

    async def _generate_ready_step(
        self,
        *,
        index: int,
        step: QueryPlanStep,
        total_steps: int,
        message: str,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        retry_feedback_by_step: dict[str, list[dict[str, Any]]],
        interpretation_notes: list[str],
        caveats: list[str],
        assumptions: list[str],
        progress_callback: ProgressFn | None,
        sync_retry_feedback: Callable[[], None],
        temporal_scope: TemporalScope | None,
        dependency_context: list[dict[str, Any]] | None = None,
        start_attempt: int = 1,
    ) -> tuple[GeneratedStep, int]:
        step_retry_feedback = retry_feedback_by_step.setdefault(step.id, [])
        attempt = max(1, start_attempt)
        generation_history = list(history)
        while True:
            if attempt == 1:
                await emit_progress(progress_callback, f"Preparing data retrieval step {index + 1}/{total_steps}: {step.goal}")
                if self._analyst_fn is not None:
                    await emit_progress(
                        progress_callback,
                        f"Preparing data retrieval for step {index + 1}/{total_steps}",
                    )
                else:
                    await emit_progress(progress_callback, f"Preparing data retrieval for step {index + 1}/{total_steps}")
            else:
                await emit_progress(
                    progress_callback,
                    f"Refining data retrieval for step {index + 1}/{total_steps} (attempt {attempt}/{MAX_SQL_ATTEMPTS})",
                )

            generated = await self._generator.generate(
                index=index,
                message=message,
                step=step,
                history=generation_history,
                prior_sql=prior_sql,
                conversation_id=conversation_id,
                attempt_number=attempt,
                retry_feedback=step_retry_feedback,
                temporal_scope=temporal_scope.model_dump(mode="json", exclude_none=True) if temporal_scope else None,
                dependency_context=dependency_context,
            )
            append_unique(interpretation_notes, generated.interpretation_notes, limit=6)
            append_unique(caveats, generated.caveats, limit=8)
            append_unique(assumptions, generated.assumptions, limit=8)

            if generated.status == "sql_ready" and generated.sql:
                return generated, attempt

            failure_code = failure_code_for_generated(generated)
            is_generation_retryable = (
                generated.status == "clarification"
                and generated.clarification_kind == "technical_failure"
                and attempt < MAX_SQL_ATTEMPTS
            )
            is_dependency_context_retryable = (
                generated.status == "clarification"
                and generated.clarification_kind == "user_input_required"
                and bool(dependency_context)
                and attempt < MAX_SQL_ATTEMPTS
            )
            if is_generation_retryable or is_dependency_context_retryable:
                failure_text = generated.clarification_question or generated.rationale or "technical SQL generation failure"
                step_retry_feedback.append(
                    build_retry_event(
                        code=failure_code,
                        step_id=generated.step.id,
                        attempt=attempt,
                        provider=generated.provider,
                        error=failure_text,
                        failed_sql=generated.attempted_sql or generated.sql,
                        clarification_question=generated.clarification_question,
                        clarification_kind=generated.clarification_kind,
                    )
                )
                sync_retry_feedback()
                if is_dependency_context_retryable:
                    generation_history = [
                        *generation_history,
                        (
                            "Dependency context from prerequisite steps is already available. "
                            "Use that context to derive entity scope; do not ask the user for entity IDs/top-N."
                        ),
                    ]
                else:
                    generation_history = [
                        *generation_history,
                        f"Previous SQL generation failed for {generated.step.id}: {failure_text}",
                    ]
                attempt += 1
                continue

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
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        retry_feedback_by_step: dict[str, list[dict[str, Any]]],
        interpretation_notes: list[str],
        caveats: list[str],
        assumptions: list[str],
        progress_callback: ProgressFn | None,
        sync_retry_feedback: Callable[[], None],
        temporal_scope: TemporalScope | None,
        dependency_context: list[dict[str, Any]] | None = None,
    ) -> tuple[int, SqlExecutionResult]:
        current_generated = generated
        attempt_cursor = generated_attempt
        step_retry_feedback = retry_feedback_by_step.setdefault(current_generated.step.id, [])
        step_started_at = perf_counter()

        while True:
            try:
                index, result = await self._execute_generated_step(
                    generated=current_generated,
                    total_steps=total_steps,
                    progress_callback=progress_callback,
                )
                if temporal_scope is not None:
                    mismatch_reason = validate_temporal_scope_result(result, temporal_scope)
                    if mismatch_reason:
                        raise TemporalScopeMismatchError(mismatch_reason)
                return index, result
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
                    if isinstance(error, AllNullRowsError)
                    else (
                        SqlFailureCode.EXECUTION_TEMPORAL_MISMATCH
                        if isinstance(error, TemporalScopeMismatchError)
                        else (
                        SqlFailureCode.EXECUTION_TIMEOUT
                        if is_timeout_error(error)
                        else SqlFailureCode.EXECUTION_WAREHOUSE_ERROR
                        )
                    )
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
                elapsed_seconds = perf_counter() - step_started_at

                if failure_code == SqlFailureCode.EXECUTION_TIMEOUT or elapsed_seconds >= settings.sql_step_sla_seconds:
                    timeout_text = error_text or "SQL execution exceeded SLA."
                    raise_execution_timeout(
                        generated=current_generated,
                        attempt=attempt_cursor,
                        retry_feedback=step_retry_feedback,
                        error_text=timeout_text,
                        elapsed_seconds=elapsed_seconds,
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

                await emit_progress(
                    progress_callback,
                    (
                        f"Data retrieval step {current_generated.index + 1}/{total_steps} failed on attempt {attempt_cursor}: "
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
                        history=retry_history,
                        prior_sql=prior_sql,
                        conversation_id=conversation_id,
                        retry_feedback_by_step=retry_feedback_by_step,
                        interpretation_notes=interpretation_notes,
                        caveats=caveats,
                        assumptions=assumptions,
                        progress_callback=progress_callback,
                        sync_retry_feedback=sync_retry_feedback,
                        temporal_scope=temporal_scope,
                        dependency_context=dependency_context,
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
        plan: list[QueryPlanStep],
        history: list[str],
        conversation_id: str = "anonymous",
        temporal_scope: TemporalScope | None = None,
        progress_callback: ProgressFn | None = None,
    ) -> SqlStageOutcome:
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
                return SqlStageOutcome(results=[], interpretation_notes=[], caveats=[], assumptions=[])
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
            await emit_progress(
                progress_callback,
                f"Dispatching {total_steps} data retrieval step(s) to {dispatch.target_label}",
            )
            levels = dependency_levels(plan)
            dependencies_by_index = dependency_indices(plan)
            generation_semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))
            execution_semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))

            prior_sql: list[str] = []
            interpretation_notes: list[str] = []
            caveats: list[str] = []
            assumptions: list[str] = []
            generated_attempt_by_index: dict[int, int] = {}
            retry_feedback_by_step: dict[str, list[dict[str, Any]]] = {}
            results_by_index: dict[int, SqlExecutionResult] = {}

            def _sync_retry_feedback() -> None:
                self._latest_retry_feedback = self._flatten_retry_feedback(retry_feedback_by_step)

            # Process each dependency level as generate -> execute so downstream
            # levels can consume upstream result context.
            for level in levels:
                snapshot_prior_sql = list(prior_sql)

                async def _generate(index: int) -> tuple[GeneratedStep, int]:
                    async with generation_semaphore:
                        step = plan[index]
                        dependency_context = self._dependency_context_for_step(
                            index=index,
                            dependencies_by_index=dependencies_by_index,
                            plan=plan,
                            results_by_index=results_by_index,
                        )
                        return await self._generate_ready_step(
                            index=index,
                            step=step,
                            total_steps=total_steps,
                            message=message,
                            history=history,
                            prior_sql=snapshot_prior_sql,
                            conversation_id=conversation_id,
                            retry_feedback_by_step=retry_feedback_by_step,
                            interpretation_notes=interpretation_notes,
                            caveats=caveats,
                            assumptions=assumptions,
                            progress_callback=progress_callback,
                            sync_retry_feedback=_sync_retry_feedback,
                            temporal_scope=temporal_scope,
                            dependency_context=dependency_context,
                        )

                generated_level = (
                    await asyncio.gather(*(_generate(index) for index in level))
                    if len(level) > 1
                    else [await _generate(level[0])]
                )
                ordered_generated_level = sorted(generated_level, key=lambda item: item[0].index)
                for generated, generated_attempt in ordered_generated_level:
                    prior_sql.append(generated.sql)
                    generated_attempt_by_index[generated.index] = generated_attempt

                generated_level_steps = [generated for generated, _ in ordered_generated_level]
                should_parallel_execute = len(generated_level) > 1 and dispatch.parallel_capable
                level_positions = ", ".join(str(index + 1) for index in level)
                await emit_progress(
                    progress_callback,
                    (
                        f"Executing level [{level_positions}] in parallel on {dispatch.target_label}"
                        if should_parallel_execute
                        else f"Executing level [{level_positions}] serially on {dispatch.target_label}"
                    ),
                )

                async def _execute(generated: GeneratedStep) -> tuple[int, SqlExecutionResult]:
                    async with execution_semaphore:
                        dependency_context = self._dependency_context_for_step(
                            index=generated.index,
                            dependencies_by_index=dependencies_by_index,
                            plan=plan,
                            results_by_index=results_by_index,
                        )
                        return await self._execute_with_retries(
                            generated=generated,
                            generated_attempt=generated_attempt_by_index.get(generated.index, 1),
                            total_steps=total_steps,
                            message=message,
                            history=history,
                            prior_sql=prior_sql,
                            conversation_id=conversation_id,
                            retry_feedback_by_step=retry_feedback_by_step,
                            interpretation_notes=interpretation_notes,
                            caveats=caveats,
                            assumptions=assumptions,
                            progress_callback=progress_callback,
                            sync_retry_feedback=_sync_retry_feedback,
                            temporal_scope=temporal_scope,
                            dependency_context=dependency_context,
                        )

                level_results = (
                    await asyncio.gather(*(_execute(generated) for generated in generated_level_steps))
                    if should_parallel_execute
                    else [await _execute(generated) for generated in generated_level_steps]
                )
                for index, result in level_results:
                    results_by_index[index] = result

            results = [results_by_index[index] for index in range(total_steps)]
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
            return SqlStageOutcome(
                results=results,
                interpretation_notes=interpretation_notes[:6],
                caveats=caveats[:8],
                assumptions=assumptions[:8],
            )
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
