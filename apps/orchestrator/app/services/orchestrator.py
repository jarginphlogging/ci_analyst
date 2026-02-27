from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar
from uuid import uuid4

from app.models import (
    AgentResponse,
    ChatTurnRequest,
    SqlExecutionResult,
    StreamResult,
    TraceStep,
    TurnResult,
    ValidationResult,
    now_iso,
)
from app.services.llm_trace import LlmTraceCollector, LlmTraceEntry, bind_llm_trace_collector
from app.services.stages import PlannerBlockedError, SqlGenerationBlockedError
from app.services.stages.synthesis_stage import build_incremental_answer_deltas
from app.services.types import OrchestratorDependencies, TurnExecutionContext

T = TypeVar("T")
ProgressCallback = Callable[[str], Awaitable[None]]
GENERIC_FAILURE_MESSAGE = "I couldn't complete that request. Please review the trace for details."
GENERIC_FAILURE_WHY = "The request did not produce a governed result."


class ConversationalOrchestrator:
    def __init__(self, dependencies: OrchestratorDependencies):
        self._dependencies = dependencies
        self._session_history: dict[str, list[str]] = {}

    def _session_context(self, request: ChatTurnRequest) -> tuple[str, list[str]]:
        session_id = str(request.sessionId or "anonymous")
        history = self._session_history.get(session_id, [])
        prior_history = history[-8:]
        history.append(request.message)
        self._session_history[session_id] = history[-12:]
        return session_id, prior_history

    async def _run_with_heartbeat(
        self,
        *,
        operation: Callable[[], Awaitable[T]],
        progress_callback: ProgressCallback,
        heartbeat_message: str,
        interval_seconds: float = 1.5,
    ) -> T:
        task = asyncio.create_task(operation())
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=interval_seconds)
            except asyncio.TimeoutError:
                await progress_callback(heartbeat_message)

    async def _execute_pipeline(
        self,
        request: ChatTurnRequest,
        prior_history: list[str],
        progress_callback: ProgressCallback,
    ) -> tuple[TurnExecutionContext, list[SqlExecutionResult], ValidationResult]:
        await progress_callback("Building governed plan")
        try:
            context = await self._run_with_heartbeat(
                operation=lambda: self._dependencies.create_plan(request, prior_history),
                progress_callback=progress_callback,
                heartbeat_message="Building plan...",
            )
        except PlannerBlockedError as blocked:
            raise
        await progress_callback(f"Plan ready with {len(context.plan)} step(s)")

        await progress_callback("Executing SQL and retrieving result tables")
        try:
            results = await self._run_with_heartbeat(
                operation=lambda: self._dependencies.run_sql(
                    request,
                    context,
                    prior_history,
                    progress_callback=progress_callback,
                ),
                progress_callback=progress_callback,
                heartbeat_message="Executing governed SQL...",
            )
        except SqlGenerationBlockedError as blocked:
            blocked.context = context
            raise
        except Exception as error:  # noqa: BLE001
            blocked = SqlGenerationBlockedError(
                stop_reason="technical_failure",
                user_message=(
                    "The SQL stage failed unexpectedly before a governed result was returned. "
                    "Please review the trace and retry."
                ),
                detail={
                    "phase": "sql_execution",
                    "error": str(error),
                    "message": request.message,
                },
            )
            blocked.context = context
            raise blocked from error

        await progress_callback("Running numeric QA and consistency checks")
        validation = await self._dependencies.validate_results(results)

        if not validation.passed:
            raise RuntimeError("Result validation failed.")
        return context, results, validation

    @staticmethod
    def _preview_text(text: str, max_chars: int = 220) -> str:
        collapsed = " ".join(text.split())
        if len(collapsed) <= max_chars:
            return collapsed
        return f"{collapsed[: max_chars - 3]}..."

    def _history_summary(self, history: list[str]) -> dict[str, Any]:
        return {
            "historyDepth": len(history),
            "recentTurns": [self._preview_text(turn, max_chars=140) for turn in history[-3:]],
        }

    def _plan_summary(self, context: TurnExecutionContext) -> dict[str, Any]:
        return {
            "analysisType": context.analysis_type,
            "secondaryAnalysisType": context.secondary_analysis_type,
            "stepCount": len(context.plan),
            "steps": [
                {
                    "id": step.id,
                    "goal": self._preview_text(step.goal, max_chars=180),
                    "dependsOn": step.dependsOn,
                    "independent": step.independent,
                }
                for step in context.plan
            ],
        }

    def _result_row_sample(self, row: dict[str, Any], max_columns: int = 8) -> dict[str, Any]:
        sampled: dict[str, Any] = {}
        column_items = list(row.items())[:max_columns]
        for key, value in column_items:
            if isinstance(value, str):
                sampled[key] = self._preview_text(value, max_chars=90)
            elif isinstance(value, (int, float, bool)) or value is None:
                sampled[key] = value
            else:
                sampled[key] = self._preview_text(str(value), max_chars=90)
        if len(row) > max_columns:
            sampled["__truncatedColumns"] = len(row) - max_columns
        return sampled

    def _results_summary(self, results: list[SqlExecutionResult]) -> dict[str, Any]:
        step_summaries = []
        for index, result in enumerate(results, start=1):
            sample_rows = [self._result_row_sample(row) for row in result.rows[:2]]
            column_count = len(result.rows[0]) if result.rows else 0
            step_summaries.append(
                {
                    "stepIndex": index,
                    "rowCount": result.rowCount,
                    "columnCount": column_count,
                    "sqlPreview": self._preview_text(result.sql, max_chars=260),
                    "sampleRows": sample_rows,
                }
            )

        return {
            "queryCount": len(results),
            "totalRows": sum(result.rowCount for result in results),
            "steps": step_summaries,
        }

    def _response_summary(self, response: AgentResponse) -> dict[str, Any]:
        return {
            "analysisType": response.analysisType,
            "secondaryAnalysisType": response.secondaryAnalysisType,
            "confidence": response.confidence,
            "answerPreview": self._preview_text(response.answer, max_chars=260),
            "metricLabels": [metric.label for metric in response.metrics[:5]],
            "summaryCardLabels": [card.label for card in response.summaryCards[:5]],
            "primaryVisual": response.primaryVisual.model_dump() if response.primaryVisual else None,
            "insightTitles": [insight.title for insight in response.insights[:5]],
            "suggestedQuestions": response.suggestedQuestions[:3],
            "tableCount": len(response.dataTables),
            "artifactCount": len(response.artifacts),
        }

    def _llm_entries_for_stages(self, llm_entries: list[LlmTraceEntry], stage_names: set[str]) -> list[LlmTraceEntry]:
        return [entry for entry in llm_entries if entry.stage in stage_names]

    def _llm_prompt_payload(self, llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
        return [
            {
                "provider": entry.provider,
                "metadata": entry.metadata,
                "systemPrompt": entry.system_prompt,
                "userPrompt": entry.user_prompt,
                "maxTokens": entry.max_tokens,
                "temperature": entry.temperature,
            }
            for entry in llm_entries
        ]

    def _llm_response_payload(self, llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
        return [
            {
                "provider": entry.provider,
                "metadata": entry.metadata,
                "rawResponse": entry.raw_response,
                "parsedResponse": entry.parsed_response,
                "error": entry.error,
            }
            for entry in llm_entries
        ]

    def _sql_retry_feedback(self, llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in llm_entries:
            metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
            raw_feedback = metadata.get("retryFeedback")
            if not isinstance(raw_feedback, list):
                continue
            for item in raw_feedback:
                if not isinstance(item, dict):
                    continue
                key = str(item)
                if key in seen:
                    continue
                seen.add(key)
                collected.append(item)
        return collected[:6]

    @staticmethod
    def _warehouse_errors(retry_feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for item in retry_feedback:
            phase = str(item.get("phase", "")).strip().lower()
            error = item.get("error")
            if "sql_execution" not in phase and "sql_regeneration_blocked" not in phase:
                continue
            if not isinstance(error, str) or not error.strip():
                continue
            errors.append(item)
        return errors[:6]

    def _build_trace(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        validation: ValidationResult,
        response: AgentResponse,
        phase: str,
        llm_entries: list[LlmTraceEntry],
    ) -> list[TraceStep]:
        result_summary = self._results_summary(results)
        synthesis_summary = "Prepared deterministic draft summary from retrieved SQL tables."
        if phase == "final":
            synthesis_summary = "Synthesized final narrative and recommendations from governed execution context."
        plan_llm_entries = self._llm_entries_for_stages(llm_entries, {"plan_generation"})
        sql_llm_entries = self._llm_entries_for_stages(llm_entries, {"sql_generation"})
        synthesis_llm_entries = self._llm_entries_for_stages(llm_entries, {"synthesis_final"}) if phase == "final" else []
        sql_retry_feedback = context.sql_retry_feedback or self._sql_retry_feedback(sql_llm_entries)
        warehouse_errors = self._warehouse_errors(sql_retry_feedback)

        return [
            TraceStep(
                id="t1",
                title="Build plan",
                summary="Generated ordered analysis plan under semantic-model policy guardrails.",
                status="done",
                stageInput={
                    "message": request.message,
                    **self._history_summary(prior_history),
                    "llmPrompts": self._llm_prompt_payload(plan_llm_entries),
                },
                stageOutput={
                    **self._plan_summary(context),
                    "llmResponses": self._llm_response_payload(plan_llm_entries),
                },
            ),
            TraceStep(
                id="t2",
                title="Generate and execute SQL",
                summary="Generated governed SQL for each plan step and executed against the analytics provider.",
                status="done",
                sql=results[0].sql if results else None,
                stageInput={
                    "planStepIds": [step.id for step in context.plan],
                    "planGoals": [self._preview_text(step.goal, max_chars=120) for step in context.plan],
                    "historyDepth": len(prior_history),
                    "llmPrompts": self._llm_prompt_payload(sql_llm_entries),
                },
                stageOutput={
                    **result_summary,
                    "executionNotes": context.sql_assumptions,
                    "retryFeedback": sql_retry_feedback,
                    "warehouseErrors": warehouse_errors,
                    "llmResponses": self._llm_response_payload(sql_llm_entries),
                },
            ),
            TraceStep(
                id="t3",
                title="Validate results",
                summary="Applied numeric and policy quality checks to ensure returned tables are usable.",
                status="done" if validation.passed else "blocked",
                qualityChecks=validation.checks,
                stageInput={
                    "queryCount": len(results),
                    "rowCounts": [result.rowCount for result in results],
                    "totalRows": result_summary["totalRows"],
                },
                stageOutput={
                    "passed": validation.passed,
                    "checks": validation.checks,
                },
            ),
            TraceStep(
                id="t4",
                title="Synthesize response",
                summary=synthesis_summary,
                status="done",
                stageInput={
                    "phase": phase,
                    "sqlAssumptionCount": len(context.sql_assumptions),
                    "resultSummary": result_summary,
                    "llmPrompts": self._llm_prompt_payload(synthesis_llm_entries),
                },
                stageOutput={
                    **self._response_summary(response),
                    "llmResponses": self._llm_response_payload(synthesis_llm_entries),
                },
            ),
        ]

    def _planner_blocked_trace_step(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        blocked: PlannerBlockedError,
        llm_entries: list[LlmTraceEntry],
    ) -> TraceStep:
        planner_llm_entries = self._llm_entries_for_stages(llm_entries, {"plan_generation"})
        return TraceStep(
            id="t1",
            title="Build plan",
            summary="Planner blocked execution and returned a guidance response.",
            status="blocked",
            stageInput={
                "message": request.message,
                **self._history_summary(prior_history),
                "llmPrompts": self._llm_prompt_payload(planner_llm_entries),
            },
            stageOutput={
                "stopReason": blocked.stop_reason,
                "userMessage": blocked.user_message,
                "llmResponses": self._llm_response_payload(planner_llm_entries),
            },
        )

    def _planner_completed_trace_step(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        context: TurnExecutionContext,
        llm_entries: list[LlmTraceEntry],
    ) -> TraceStep:
        planner_llm_entries = self._llm_entries_for_stages(llm_entries, {"plan_generation"})
        return TraceStep(
            id="t1",
            title="Build plan",
            summary="Generated ordered analysis plan under semantic-model policy guardrails.",
            status="done",
            stageInput={
                "message": request.message,
                **self._history_summary(prior_history),
                "llmPrompts": self._llm_prompt_payload(planner_llm_entries),
            },
            stageOutput={
                **self._plan_summary(context),
                "llmResponses": self._llm_response_payload(planner_llm_entries),
            },
        )

    def _sql_generation_blocked_trace_step(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        context: TurnExecutionContext,
        blocked: SqlGenerationBlockedError,
        llm_entries: list[LlmTraceEntry],
    ) -> TraceStep:
        sql_llm_entries = self._llm_entries_for_stages(llm_entries, {"sql_generation"})
        detail_retry_feedback = blocked.detail.get("retryFeedback") if blocked.detail else None
        if isinstance(detail_retry_feedback, list):
            retry_feedback = [item for item in detail_retry_feedback if isinstance(item, dict)]
        else:
            retry_feedback = context.sql_retry_feedback or self._sql_retry_feedback(sql_llm_entries)
        stage_output: dict[str, Any] = {
            "stopReason": blocked.stop_reason,
            "userMessage": blocked.user_message,
            "retryFeedback": retry_feedback,
            "warehouseErrors": self._warehouse_errors(retry_feedback),
            "llmResponses": self._llm_response_payload(sql_llm_entries),
        }
        derived_failed_sql = ""
        for entry in sql_llm_entries:
            parsed = entry.parsed_response if isinstance(entry.parsed_response, dict) else None
            if not parsed:
                continue
            candidate = parsed.get("failedSql")
            if not candidate:
                candidate = parsed.get("sql")
            if isinstance(candidate, str) and candidate.strip():
                derived_failed_sql = candidate
                break
        if blocked.detail:
            stage_output["failureDetail"] = blocked.detail
            failed_sql = blocked.detail.get("failedSql")
            if isinstance(failed_sql, str) and failed_sql.strip():
                stage_output["failedSql"] = failed_sql
            elif derived_failed_sql:
                stage_output["failedSql"] = derived_failed_sql
        elif derived_failed_sql:
            stage_output["failedSql"] = derived_failed_sql
        return TraceStep(
            id="t2",
            title="Generate and execute SQL",
            summary="SQL generation blocked and returned guidance.",
            status="blocked",
            stageInput={
                "message": request.message,
                "planStepIds": [step.id for step in context.plan],
                **self._history_summary(prior_history),
                "llmPrompts": self._llm_prompt_payload(sql_llm_entries),
            },
            stageOutput=stage_output,
        )

    def _trace_until_sql_failure(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        context: TurnExecutionContext,
        blocked: SqlGenerationBlockedError,
        llm_entries: list[LlmTraceEntry],
    ) -> list[TraceStep]:
        return [
            self._planner_completed_trace_step(
                request=request,
                prior_history=prior_history,
                context=context,
                llm_entries=llm_entries,
            ),
            self._sql_generation_blocked_trace_step(
                request=request,
                prior_history=prior_history,
                context=context,
                blocked=blocked,
                llm_entries=llm_entries,
            ),
        ]

    def _finalize_response(
        self,
        *,
        response: AgentResponse,
        validation: ValidationResult,
        session_depth: int,
    ) -> AgentResponse:
        validation_step_id = "t3" if any(step.id == "t3" for step in response.trace) else "t4"
        response.trace = [
            (step.model_copy(update={"qualityChecks": validation.checks}) if step.id == validation_step_id else step)
            for step in response.trace
        ]

        assumptions = [
            *response.assumptions,
            "Standard execution pipeline was used.",
            f"Session memory depth: {session_depth} turn(s).",
        ]
        deduped: list[str] = []
        for item in assumptions:
            if item not in deduped:
                deduped.append(item)
        response.assumptions = deduped
        return response

    def _unexpected_failure_response(
        self,
        *,
        request: ChatTurnRequest,
        prior_history: list[str],
        llm_entries: list[LlmTraceEntry],
        error: Exception,
    ) -> AgentResponse:
        return AgentResponse(
            answer=GENERIC_FAILURE_MESSAGE,
            confidence="low",
            whyItMatters=GENERIC_FAILURE_WHY,
            metrics=[],
            evidence=[],
            insights=[],
            suggestedQuestions=[],
            assumptions=[],
            trace=[
                TraceStep(
                    id="t0",
                    title="Pipeline failure",
                    summary="Execution failed before a governed response could be produced.",
                    status="blocked",
                    stageInput={
                        "message": request.message,
                        **self._history_summary(prior_history),
                        "llmPrompts": self._llm_prompt_payload(llm_entries),
                    },
                    stageOutput={
                        "error": str(error),
                        "llmResponses": self._llm_response_payload(llm_entries),
                    },
                )
            ],
            dataTables=[],
            artifacts=[],
        )

    def _planner_blocked_response(
        self,
        *,
        blocked: PlannerBlockedError,
        session_depth: int,
        trace_step: TraceStep | None = None,
    ) -> AgentResponse:
        _ = session_depth

        return AgentResponse(
            answer=GENERIC_FAILURE_MESSAGE,
            confidence="low",
            whyItMatters=GENERIC_FAILURE_WHY,
            metrics=[],
            evidence=[],
            insights=[],
            suggestedQuestions=[],
            assumptions=[],
            trace=[
                trace_step
                or TraceStep(
                    id="t1",
                    title="Build plan",
                    summary="Planner blocked execution and returned a guidance response.",
                    status="blocked",
                    stageOutput={
                        "stopReason": blocked.stop_reason,
                        "userMessage": blocked.user_message,
                    },
                )
            ],
            dataTables=[],
            artifacts=[],
        )

    def _sql_generation_blocked_response(
        self,
        *,
        blocked: SqlGenerationBlockedError,
        session_depth: int,
        trace_steps: list[TraceStep] | None = None,
    ) -> AgentResponse:
        _ = session_depth
        why = (
            "SQL generation/execution is blocked until this clarification is resolved."
            if blocked.stop_reason == "clarification"
            else "SQL generation/execution failed due to a technical issue. Review trace details and retry."
        )

        return AgentResponse(
            answer=blocked.user_message,
            confidence="low",
            whyItMatters=why,
            metrics=[],
            evidence=[],
            insights=[],
            suggestedQuestions=[],
            assumptions=[],
            trace=trace_steps
            or [
                TraceStep(
                    id="t2",
                    title="Generate and execute SQL",
                    summary="SQL generation blocked and returned guidance.",
                    status="blocked",
                    stageOutput={
                        "stopReason": blocked.stop_reason,
                        "userMessage": blocked.user_message,
                    },
                )
            ],
            dataTables=[],
            artifacts=[],
        )

    async def run_turn(self, request: ChatTurnRequest) -> TurnResult:
        session_id, prior_history = self._session_context(request)
        llm_collector = LlmTraceCollector()

        async def _noop_progress(_: str) -> None:
            return None

        try:
            with bind_llm_trace_collector(llm_collector):
                context, results, validation = await self._execute_pipeline(request, prior_history, _noop_progress)
                response = await self._dependencies.build_response(request, context, results, prior_history)
                response.trace = self._build_trace(
                    request=request,
                    prior_history=prior_history,
                    context=context,
                    results=results,
                    validation=validation,
                    response=response,
                    phase="final",
                    llm_entries=llm_collector.entries,
                )
                response = self._finalize_response(
                    response=response,
                    validation=validation,
                    session_depth=len(self._session_history.get(session_id, [])),
                )
        except PlannerBlockedError as blocked:
            response = self._planner_blocked_response(
                blocked=blocked,
                session_depth=len(self._session_history.get(session_id, [])),
                trace_step=self._planner_blocked_trace_step(
                    request=request,
                    prior_history=prior_history,
                    blocked=blocked,
                    llm_entries=llm_collector.entries,
                ),
            )
            return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)
        except SqlGenerationBlockedError as blocked:
            blocked_context = getattr(blocked, "context", TurnExecutionContext(route="standard", plan=[]))
            response = self._sql_generation_blocked_response(
                blocked=blocked,
                session_depth=len(self._session_history.get(session_id, [])),
                trace_steps=self._trace_until_sql_failure(
                    request=request,
                    prior_history=prior_history,
                    context=blocked_context,
                    blocked=blocked,
                    llm_entries=llm_collector.entries,
                ),
            )
            return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)
        except Exception as error:  # noqa: BLE001
            response = self._unexpected_failure_response(
                request=request,
                prior_history=prior_history,
                llm_entries=llm_collector.entries,
                error=error,
            )
            return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

        return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

    async def stream_events(self, request: ChatTurnRequest) -> AsyncIterator[dict[str, Any]]:
        session_id, prior_history = self._session_context(request)
        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await event_queue.put(event)

        async def progress(message: str) -> None:
            await emit({"type": "status", "message": message})

        async def worker() -> None:
            llm_collector = LlmTraceCollector()
            try:
                with bind_llm_trace_collector(llm_collector):
                    await progress("Understanding query intent and scope")
                    try:
                        context, results, validation = await self._execute_pipeline(
                            request,
                            prior_history,
                            progress,
                        )
                    except PlannerBlockedError as blocked:
                        await progress("Planner guardrail triggered; returning guidance response")
                        blocked_response = self._planner_blocked_response(
                            blocked=blocked,
                            session_depth=len(self._session_history.get(session_id, [])),
                            trace_step=self._planner_blocked_trace_step(
                                request=request,
                                prior_history=prior_history,
                                blocked=blocked,
                                llm_entries=llm_collector.entries,
                            ),
                        )
                        await emit({"type": "response", "phase": "final", "response": blocked_response.model_dump()})
                        await emit({"type": "done"})
                        return
                    except SqlGenerationBlockedError as blocked:
                        await progress(f"SQL stage blocked: {blocked.user_message}")
                        blocked_context = getattr(blocked, "context", TurnExecutionContext(route="standard", plan=[]))
                        blocked_response = self._sql_generation_blocked_response(
                            blocked=blocked,
                            session_depth=len(self._session_history.get(session_id, [])),
                            trace_steps=self._trace_until_sql_failure(
                                request=request,
                                prior_history=prior_history,
                                context=blocked_context,
                                blocked=blocked,
                                llm_entries=llm_collector.entries,
                            ),
                        )
                        await emit({"type": "response", "phase": "final", "response": blocked_response.model_dump()})
                        await emit({"type": "done"})
                        return

                    await progress("Preparing initial answer from retrieved data")
                    fast_response = await self._run_with_heartbeat(
                        operation=lambda: self._dependencies.build_fast_response(request, context, results, prior_history),
                        progress_callback=progress,
                        heartbeat_message="Building initial answer...",
                    )
                    fast_response.trace = self._build_trace(
                        request=request,
                        prior_history=prior_history,
                        context=context,
                        results=results,
                        validation=validation,
                        response=fast_response,
                        phase="draft",
                        llm_entries=llm_collector.entries,
                    )
                    fast_response = self._finalize_response(
                        response=fast_response,
                        validation=validation,
                        session_depth=len(self._session_history.get(session_id, [])),
                    )
                    await emit({"type": "response", "phase": "draft", "response": fast_response.model_dump()})

                    await progress("Generating final narrative and recommendations")
                    final_response = await self._run_with_heartbeat(
                        operation=lambda: self._dependencies.build_response(request, context, results, prior_history),
                        progress_callback=progress,
                        heartbeat_message="Synthesizing narrative...",
                    )
                    final_response.trace = self._build_trace(
                        request=request,
                        prior_history=prior_history,
                        context=context,
                        results=results,
                        validation=validation,
                        response=final_response,
                        phase="final",
                        llm_entries=llm_collector.entries,
                    )
                    final_response = self._finalize_response(
                        response=final_response,
                        validation=validation,
                        session_depth=len(self._session_history.get(session_id, [])),
                    )

                    for delta in build_incremental_answer_deltas(fast_response.answer, final_response.answer):
                        await emit({"type": "answer_delta", "delta": delta})

                    await progress("Finalizing response payload and audit trace")
                    await emit({"type": "response", "phase": "final", "response": final_response.model_dump()})
                    await emit({"type": "done"})
            except Exception as error:  # noqa: BLE001
                failure_response = self._unexpected_failure_response(
                    request=request,
                    prior_history=prior_history,
                    llm_entries=llm_collector.entries,
                    error=error,
                )
                await emit({"type": "response", "phase": "final", "response": failure_response.model_dump()})
                await emit({"type": "done"})
            finally:
                await event_queue.put(None)

        worker_task = asyncio.create_task(worker())
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not worker_task.done():
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    async def run_stream(self, request: ChatTurnRequest) -> StreamResult:
        events: list[dict[str, Any]] = []
        final_response: AgentResponse | None = None

        async for event in self.stream_events(request):
            events.append(event)
            if event.get("type") == "response":
                response_payload = event.get("response")
                if isinstance(response_payload, dict):
                    final_response = AgentResponse.model_validate(response_payload)

        if final_response is None:
            raise RuntimeError("Streaming ended before a response payload was produced.")

        return StreamResult(
            events=events,
            turn=TurnResult(
                turnId=str(uuid4()),
                createdAt=now_iso(),
                response=final_response,
            ),
        )
