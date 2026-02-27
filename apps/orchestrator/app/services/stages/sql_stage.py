from __future__ import annotations

import asyncio
import inspect
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
        raw_rows = await self._sql_fn(sql)
        normalized_rows = normalize_rows(raw_rows)
        return SqlExecutionResult(
            sql=sql,
            rows=normalized_rows,
            rowCount=len(normalized_rows),
        )

    @staticmethod
    def _technical_failure_message(step_id: str) -> str:
        return (
            f"SQL generation/execution failed for {step_id} after technical retries. "
            "Review the trace and failed SQL, then retry."
        )

    @staticmethod
    def _blocked_from_generated(
        generated: GeneratedStep,
        *,
        attempt: int,
        retry_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationBlockedError:
        failed_sql = generated.attempted_sql or generated.sql
        retry_tail = (retry_feedback or [])[-4:]
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
                    "retryFeedback": retry_tail,
                },
            )

        if generated.status == "technical_failure":
            return SqlGenerationBlockedError(
                stop_reason="technical_failure",
                user_message=SqlExecutionStage._technical_failure_message(generated.step.id),
                detail={
                    "phase": "sql_generation",
                    "stepId": generated.step.id,
                    "attempt": attempt,
                    "provider": generated.provider,
                    "technicalError": generated.technical_error,
                    "rationale": generated.rationale,
                    "assumptions": generated.assumptions,
                    "failedSql": failed_sql,
                    "retryFeedback": retry_tail,
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
                "assumptions": generated.assumptions,
                "failedSql": failed_sql,
                "retryFeedback": retry_tail,
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
        if generated.status == "technical_failure":
            return True
        if generated.status != "clarification":
            return False
        if any("retry limit reached" in item.lower() for item in generated.assumptions):
            return False
        if generated.attempted_sql and generated.attempted_sql.strip():
            return True
        return any("sql execution attempt" in item.lower() and "failed" in item.lower() for item in generated.assumptions)

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
        self._latest_retry_feedback = []
        total_steps = len(plan)
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
        retry_feedback_by_step: dict[str, list[dict[str, Any]]] = {}

        def _sync_retry_feedback() -> None:
            self._latest_retry_feedback = self._flatten_retry_feedback(retry_feedback_by_step)

        for level in levels:
            snapshot_prior_sql = list(prior_sql)

            async def _generate(index: int) -> GeneratedStep:
                async with generation_semaphore:
                    step = plan[index]
                    await _emit_progress(progress_callback, f"Preparing SQL step {index + 1}/{total_steps}: {step.goal}")
                    if self._analyst_fn is not None:
                        await _emit_progress(
                            progress_callback,
                            f"Generating SQL with Snowflake Cortex Analyst for step {index + 1}/{total_steps}",
                        )
                    else:
                        await _emit_progress(progress_callback, f"Drafting governed SQL for step {index + 1}/{total_steps}")
                    return await self._generator.generate(
                        index=index,
                        message=message,
                        route=route,
                        step=step,
                        history=history,
                        prior_sql=snapshot_prior_sql,
                        conversation_id=conversation_id,
                        attempt_number=1,
                        retry_feedback=retry_feedback_by_step.get(step.id, []),
                    )

            generated_level = (
                await asyncio.gather(*(_generate(index) for index in level))
                if len(level) > 1
                else [await _generate(level[0])]
            )

            for generated in sorted(generated_level, key=lambda item: item.index):
                current_generated = generated
                assumptions.extend(current_generated.assumptions[:4])
                if current_generated.rationale:
                    assumptions.append(f"{current_generated.step.id} rationale: {current_generated.rationale}")

                if current_generated.status != "sql_ready" or not current_generated.sql:
                    if self._should_retry_blocked_generation(current_generated):
                        step_retry_feedback = retry_feedback_by_step.setdefault(current_generated.step.id, [])
                        for attempt in range(2, MAX_SQL_ATTEMPTS + 1):
                            step_retry_feedback.append(
                                {
                                    "phase": "sql_generation_blocked",
                                    "stepId": current_generated.step.id,
                                    "attempt": attempt - 1,
                                    "provider": current_generated.provider,
                                    "error": (
                                        current_generated.technical_error
                                        or current_generated.clarification_question
                                        or current_generated.not_relevant_reason
                                        or "SQL generation did not return executable SQL."
                                    ),
                                    "failedSql": current_generated.attempted_sql or current_generated.sql,
                                    "clarificationQuestion": current_generated.clarification_question,
                                    "technicalError": current_generated.technical_error,
                                    "notRelevantReason": current_generated.not_relevant_reason,
                                }
                            )
                            _sync_retry_feedback()
                            assumptions.append(
                                f"SQL generation retry {attempt - 1} triggered for {current_generated.step.id} after blocked attempt."
                            )
                            await _emit_progress(
                                progress_callback,
                                f"Retrying SQL generation for step {current_generated.index + 1}/{total_steps} (attempt {attempt}/{MAX_SQL_ATTEMPTS})",
                            )
                            retry_history = [
                                *history,
                                f"Previous SQL generation was blocked for {current_generated.step.id}.",
                                (
                                    f"Previous clarification: {current_generated.clarification_question}"
                                    if current_generated.status == "clarification"
                                    else f"Previous technical error: {current_generated.technical_error or 'SQL generation failure'}"
                                ),
                                f"Previous failed SQL:\n{current_generated.attempted_sql or ''}",
                            ]
                            regenerated = await self._generator.generate(
                                index=current_generated.index,
                                message=message,
                                route=route,
                                step=current_generated.step,
                                history=retry_history,
                                prior_sql=prior_sql,
                                conversation_id=conversation_id,
                                attempt_number=attempt,
                                retry_feedback=step_retry_feedback,
                            )
                            assumptions.extend(regenerated.assumptions[:4])
                            if regenerated.rationale:
                                assumptions.append(f"{regenerated.step.id} rationale: {regenerated.rationale}")
                            current_generated = regenerated
                            if current_generated.status == "sql_ready" and current_generated.sql:
                                break

                        if current_generated.status != "sql_ready" or not current_generated.sql:
                            _sync_retry_feedback()
                            raise self._blocked_from_generated(
                                current_generated,
                                attempt=MAX_SQL_ATTEMPTS,
                                retry_feedback=step_retry_feedback,
                            )
                    else:
                        _sync_retry_feedback()
                        raise self._blocked_from_generated(
                            current_generated,
                            attempt=1,
                            retry_feedback=retry_feedback_by_step.get(current_generated.step.id, []),
                        )

                prior_sql.append(current_generated.sql)
                generated_by_index[current_generated.index] = current_generated

        generated_steps = [generated_by_index[index] for index in range(total_steps)]
        results_by_index: dict[int, SqlExecutionResult] = {}

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
                    current_generated = generated
                    step_retry_feedback = retry_feedback_by_step.setdefault(current_generated.step.id, [])
                    for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
                        try:
                            return await self._execute_generated_step(
                                generated=current_generated,
                                total_steps=total_steps,
                                progress_callback=progress_callback,
                            )
                        except Exception as error:
                            if attempt >= MAX_SQL_ATTEMPTS:
                                _sync_retry_feedback()
                                retry_feedback_tail = step_retry_feedback[-6:]
                                latest_error = str(error)
                                user_message = (
                                    SqlExecutionStage._technical_failure_message(current_generated.step.id)
                                )
                                raise SqlGenerationBlockedError(
                                    stop_reason="technical_failure",
                                    user_message=user_message,
                                    detail={
                                        "phase": "sql_execution",
                                        "stepId": current_generated.step.id,
                                        "attempt": attempt,
                                        "maxAttempts": MAX_SQL_ATTEMPTS,
                                        "error": str(error),
                                        "failedSql": current_generated.sql,
                                        "retryFeedback": retry_feedback_tail,
                                    },
                                ) from error

                            step_retry_feedback.append(
                                {
                                    "phase": "sql_execution",
                                    "stepId": current_generated.step.id,
                                    "attempt": attempt,
                                    "provider": current_generated.provider,
                                    "error": str(error),
                                    "failedSql": current_generated.sql,
                                }
                            )
                            _sync_retry_feedback()
                            assumptions.append(
                                f"SQL execution retry {attempt} failed for {current_generated.step.id}: {error}"
                            )
                            await _emit_progress(
                                progress_callback,
                                (
                                    f"SQL step {generated.index + 1}/{total_steps} failed on attempt {attempt}: "
                                    f"{error}. Regenerating and retrying."
                                ),
                            )
                            retry_history = [
                                *history,
                                f"Previous SQL execution failed for {current_generated.step.id}: {error}",
                                f"Previous SQL:\n{current_generated.sql or ''}",
                            ]
                            regenerated = await self._generator.generate(
                                index=current_generated.index,
                                message=message,
                                route=route,
                                step=current_generated.step,
                                history=retry_history,
                                prior_sql=prior_sql,
                                conversation_id=conversation_id,
                                attempt_number=attempt + 1,
                                retry_feedback=step_retry_feedback,
                            )
                            assumptions.extend(regenerated.assumptions[:4])
                            if regenerated.rationale:
                                assumptions.append(f"{regenerated.step.id} rationale: {regenerated.rationale}")

                            regeneration_round = 0
                            while regenerated.status != "sql_ready" or not regenerated.sql:
                                step_retry_feedback.append(
                                    {
                                        "phase": "sql_regeneration_blocked",
                                        "stepId": current_generated.step.id,
                                        "attempt": attempt + 1 + regeneration_round,
                                        "provider": regenerated.provider,
                                        "error": (
                                            regenerated.technical_error
                                            or regenerated.clarification_question
                                            or regenerated.not_relevant_reason
                                            or "Regeneration did not return executable SQL."
                                        ),
                                        "failedSql": regenerated.attempted_sql or regenerated.sql or current_generated.sql,
                                        "clarificationQuestion": regenerated.clarification_question,
                                        "technicalError": regenerated.technical_error,
                                        "notRelevantReason": regenerated.not_relevant_reason,
                                    }
                                )
                                _sync_retry_feedback()

                                consumed_attempts = attempt + 1 + regeneration_round
                                if consumed_attempts >= MAX_SQL_ATTEMPTS:
                                    retry_feedback_tail = step_retry_feedback[-6:]
                                    user_message = SqlExecutionStage._technical_failure_message(current_generated.step.id)
                                    raise SqlGenerationBlockedError(
                                        stop_reason="technical_failure",
                                        user_message=user_message,
                                        detail={
                                            "phase": "sql_execution",
                                            "stepId": current_generated.step.id,
                                            "attempt": consumed_attempts,
                                            "maxAttempts": MAX_SQL_ATTEMPTS,
                                            "error": str(error),
                                            "failedSql": current_generated.sql,
                                            "retryFeedback": retry_feedback_tail,
                                            "regenerationStatus": regenerated.status,
                                            "regenerationClarificationQuestion": regenerated.clarification_question,
                                            "regenerationTechnicalError": regenerated.technical_error,
                                        },
                                    ) from error

                                assumptions.append(
                                    (
                                        f"SQL regeneration returned {regenerated.status} for {current_generated.step.id}; "
                                        "retrying generation with warehouse error feedback."
                                    )
                                )
                                regeneration_round += 1
                                retry_generation_history = [
                                    *retry_history,
                                    (
                                        "Previous regeneration did not return executable SQL: "
                                        f"{regenerated.technical_error or regenerated.clarification_question or regenerated.not_relevant_reason or regenerated.status}"
                                    ),
                                ]
                                regenerated = await self._generator.generate(
                                    index=current_generated.index,
                                    message=message,
                                    route=route,
                                    step=current_generated.step,
                                    history=retry_generation_history,
                                    prior_sql=prior_sql,
                                    conversation_id=conversation_id,
                                    attempt_number=attempt + 1 + regeneration_round,
                                    retry_feedback=step_retry_feedback,
                                )
                                assumptions.extend(regenerated.assumptions[:4])
                                if regenerated.rationale:
                                    assumptions.append(f"{regenerated.step.id} rationale: {regenerated.rationale}")
                            current_generated = regenerated

                    raise SqlGenerationBlockedError(
                        stop_reason="technical_failure",
                        user_message=SqlExecutionStage._technical_failure_message(current_generated.step.id),
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
        return results, deduped_assumptions[:8]
