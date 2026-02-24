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
        self._generator = SqlStepGenerator(
            model=model,
            ask_llm_json=ask_llm_json,
            analyst_fn=analyst_fn,
        )

    async def _execute_sql(self, sql: str) -> SqlExecutionResult:
        raw_rows = await self._sql_fn(sql)
        normalized_rows = normalize_rows(raw_rows)
        return SqlExecutionResult(
            sql=sql,
            rows=normalized_rows,
            rowCount=len(normalized_rows),
        )

    @staticmethod
    def _blocked_from_generated(generated: GeneratedStep, *, attempt: int) -> SqlGenerationBlockedError:
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
                },
            )

        message = generated.clarification_question or "Could you clarify your request so I can generate the right SQL?"
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
            },
        )

    async def _execute_generated_step(
        self,
        *,
        generated: GeneratedStep,
        total_steps: int,
        progress_callback: ProgressFn | None,
    ) -> tuple[int, SqlExecutionResult]:
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
        await _emit_progress(
            progress_callback,
            f"Completed SQL step {generated.index + 1}/{total_steps} ({result.rowCount} rows)",
        )
        return generated.index, result

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
                    )

            generated_level = (
                await asyncio.gather(*(_generate(index) for index in level))
                if len(level) > 1
                else [await _generate(level[0])]
            )

            for generated in sorted(generated_level, key=lambda item: item.index):
                assumptions.extend(generated.assumptions[:4])
                if generated.rationale:
                    assumptions.append(f"{generated.step.id} rationale: {generated.rationale}")

                if generated.status != "sql_ready" or not generated.sql:
                    raise self._blocked_from_generated(generated, attempt=1)

                prior_sql.append(generated.sql)
                generated_by_index[generated.index] = generated

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
                    for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
                        try:
                            return await self._execute_generated_step(
                                generated=current_generated,
                                total_steps=total_steps,
                                progress_callback=progress_callback,
                            )
                        except Exception as error:
                            if attempt >= MAX_SQL_ATTEMPTS:
                                raise SqlGenerationBlockedError(
                                    stop_reason="clarification",
                                    user_message=(
                                        "I couldn't execute a valid query for one of the requested steps. "
                                        "Please restate the metric, grain, and time window."
                                    ),
                                    detail={
                                        "phase": "sql_execution",
                                        "stepId": current_generated.step.id,
                                        "attempt": attempt,
                                        "maxAttempts": MAX_SQL_ATTEMPTS,
                                        "error": str(error),
                                        "failedSql": current_generated.sql,
                                    },
                                ) from error

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
                            )
                            assumptions.extend(regenerated.assumptions[:4])
                            if regenerated.rationale:
                                assumptions.append(f"{regenerated.step.id} rationale: {regenerated.rationale}")
                            if regenerated.status != "sql_ready" or not regenerated.sql:
                                raise self._blocked_from_generated(regenerated, attempt=attempt + 1) from error
                            current_generated = regenerated

                    raise SqlGenerationBlockedError(
                        stop_reason="clarification",
                        user_message="Could you clarify your request so I can generate the right SQL?",
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
        return results, deduped_assumptions[:8]
