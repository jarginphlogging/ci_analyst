from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import suppress
from time import perf_counter
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
from app.observability import bind_log_context
from app.tracing import add_check_event, set_stage_output, stage_span, turn_span
from app.evaluation.inline_checks_v2_1 import (
    check_answer_sanity,
    check_pii,
    check_plan_sanity,
    check_result_sanity,
    check_sql_syntax,
    check_validation_contract,
    redact_pii,
)
from app.services.llm_trace import LlmTraceCollector, LlmTraceEntry, bind_llm_trace_collector
from app.services.stages import PlannerBlockedError, SqlGenerationBlockedError
from app.services.stages.sql_state_machine import execution_error_view, normalize_retry_feedback
from app.services.stages.synthesis_stage import build_incremental_answer_deltas
from app.services.types import OrchestratorDependencies, TurnExecutionContext
from app.config import settings

T = TypeVar("T")
ProgressCallback = Callable[[str], Awaitable[None]]
logger = logging.getLogger(__name__)


class ConversationalOrchestrator:
    def __init__(self, dependencies: OrchestratorDependencies):
        self._dependencies = dependencies
        self._session_history: dict[str, list[str]] = {}
        self._latest_inline_checks: dict[str, list[str]] = {}

    def _record_inline_check(self, *, stage_id: str, check_name: str, passed: bool, reason: str) -> None:
        outcome = f"{check_name}: {'pass' if passed else 'fail'} ({reason})"
        bucket = self._latest_inline_checks.setdefault(stage_id, [])
        if outcome not in bucket:
            bucket.append(outcome)
        add_check_event(name=check_name, passed=passed, reason=reason)

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

    @staticmethod
    def _client_progress_message(message: str) -> str:
        text = (message or "").strip()
        if not text:
            return "Retrieving data"

        replacements: list[tuple[re.Pattern[str], str]] = [
            (re.compile(r"\bSQL stage blocked\b", re.IGNORECASE), "Data retrieval blocked"),
            (re.compile(r"\bBuilding governed plan\b", re.IGNORECASE), "Planning analysis..."),
            (re.compile(r"\bBuilding plan\b", re.IGNORECASE), "Planning analysis..."),
            (
                re.compile(r"\bExecuting SQL and retrieving result tables\b", re.IGNORECASE),
                "Retrieving data and preparing result tables",
            ),
            (re.compile(r"\bExecuting governed SQL\b", re.IGNORECASE), "Retrieving data"),
            (re.compile(r"\bGenerating governed SQL\b", re.IGNORECASE), "Preparing data retrieval"),
            (re.compile(r"\bGenerating SQL for step\b", re.IGNORECASE), "Preparing data retrieval for step"),
            (re.compile(r"\bDrafting governed SQL\b", re.IGNORECASE), "Preparing data retrieval"),
            (re.compile(r"\bgoverned data retrieval\b", re.IGNORECASE), "data retrieval"),
            (re.compile(r"\bPreparing SQL step\b", re.IGNORECASE), "Preparing data retrieval step"),
            (re.compile(r"\bRegenerating SQL\b", re.IGNORECASE), "Refining data retrieval step"),
            (re.compile(r"\bRunning SQL step\b", re.IGNORECASE), "Running data retrieval step"),
            (re.compile(r"\bCompleted SQL step\b", re.IGNORECASE), "Completed data retrieval step"),
            (re.compile(r"\bDispatching (\d+) SQL step\(s\)\b", re.IGNORECASE), r"Dispatching \1 data retrieval step(s)"),
            (re.compile(r"\bNo SQL was attempted\b", re.IGNORECASE), "No data retrieval was attempted"),
        ]

        sanitized = text
        for pattern, replacement in replacements:
            sanitized = pattern.sub(replacement, sanitized)
        sanitized = re.sub(r"\bSQL\b", "data retrieval", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized or "Retrieving data"

    async def _execute_pipeline(
        self,
        request: ChatTurnRequest,
        prior_history: list[str],
        progress_callback: ProgressCallback,
    ) -> tuple[TurnExecutionContext, list[SqlExecutionResult], ValidationResult, dict[str, float]]:
        pipeline_started_at = perf_counter()
        stage_timings_ms: dict[str, float] = {}
        self._latest_inline_checks = {}
        logger.info(
            "Pipeline execution started",
            extra={
                "event": "orchestrator.pipeline.started",
                "historyDepth": len(prior_history),
                "messageChars": len(request.message),
            },
        )
        await progress_callback("Planning analysis...")
        plan_started_at = perf_counter()
        with stage_span(
            span_name="pipeline.t1_plan",
            stage_id="t1",
            input_value={
                "message": request.message,
                "historyDepth": len(prior_history),
            },
        ):
            try:
                context = await self._run_with_heartbeat(
                    operation=lambda: self._dependencies.create_plan(request, prior_history),
                    progress_callback=progress_callback,
                    heartbeat_message="Planning analysis...",
                )
            except PlannerBlockedError as blocked:
                stage_timings_ms["t1"] = round((perf_counter() - plan_started_at) * 1000, 2)
                set_stage_output(
                    {"blocked": True, "stopReason": blocked.stop_reason, "userMessage": blocked.user_message},
                    attributes={"decomposition.count": 0, "runtime.ms": stage_timings_ms["t1"]},
                )
                setattr(blocked, "stage_timings_ms", dict(stage_timings_ms))
                logger.info(
                    "Planner blocked request",
                    extra={
                        "event": "orchestrator.pipeline.plan.blocked",
                        "stopReason": blocked.stop_reason,
                        "userMessage": blocked.user_message,
                        "runtimeMs": stage_timings_ms["t1"],
                    },
                )
                raise
            stage_timings_ms["t1"] = round((perf_counter() - plan_started_at) * 1000, 2)
            plan_payload = self._plan_summary(context)
            set_stage_output(
                plan_payload,
                attributes={
                    "decomposition.count": len(context.plan),
                    "runtime.ms": stage_timings_ms["t1"],
                },
            )
            plan_checks_payload = [
                {
                    "id": step.id,
                    "goal": step.goal,
                    "dependsOn": list(step.dependsOn),
                    "independent": step.independent,
                }
                for step in context.plan
            ]
            plan_check_pass, plan_check_reason = check_plan_sanity(
                plan_checks_payload,
                max_steps=max(1, settings.plan_max_steps),
            )
            self._record_inline_check(
                stage_id="t1",
                check_name="plan_sanity",
                passed=plan_check_pass,
                reason=plan_check_reason,
            )
            if not plan_check_pass:
                logger.warning(
                    "Plan failed inline sanity checks",
                    extra={
                        "event": "orchestrator.pipeline.plan.inline_check_failed",
                        "reason": plan_check_reason,
                    },
                )
                raise PlannerBlockedError(
                    stop_reason="too_complex",
                    user_message="I need clarification before executing because the generated analysis plan failed policy checks.",
                )
            logger.info(
                "Plan created",
                extra={
                    "event": "orchestrator.pipeline.plan.completed",
                    "stepCount": len(context.plan),
                    "runtimeMs": stage_timings_ms["t1"],
                },
            )
        await progress_callback(f"Plan ready with {len(context.plan)} step(s)")

        await progress_callback("Retrieving data and preparing result tables")
        sql_started_at = perf_counter()
        with stage_span(
            span_name="pipeline.t2_sql",
            stage_id="t2",
            input_value={
                "message": request.message,
                "planStepCount": len(context.plan),
                "planStepIds": [step.id for step in context.plan],
            },
        ):
            try:
                results = await self._run_with_heartbeat(
                    operation=lambda: self._dependencies.run_sql(
                        request,
                        context,
                        prior_history,
                        progress_callback=progress_callback,
                    ),
                    progress_callback=progress_callback,
                    heartbeat_message="Retrieving data",
                )
            except SqlGenerationBlockedError as blocked:
                stage_timings_ms["t2"] = round((perf_counter() - sql_started_at) * 1000, 2)
                set_stage_output(
                    {"blocked": True, "stopReason": blocked.stop_reason, "userMessage": blocked.user_message},
                    attributes={
                        "retry.count": len(context.sql_retry_feedback),
                        "runtime.ms": stage_timings_ms["t2"],
                    },
                )
                setattr(blocked, "stage_timings_ms", dict(stage_timings_ms))
                logger.info(
                    "SQL stage blocked request",
                    extra={
                        "event": "orchestrator.pipeline.sql.blocked",
                        "stopReason": blocked.stop_reason,
                        "userMessage": blocked.user_message,
                        "detail": blocked.detail,
                        "runtimeMs": stage_timings_ms["t2"],
                    },
                )
                blocked.context = context
                raise
            except Exception as error:  # noqa: BLE001
                stage_timings_ms["t2"] = round((perf_counter() - sql_started_at) * 1000, 2)
                logger.exception(
                    "SQL stage failed unexpectedly",
                    extra={
                        "event": "orchestrator.pipeline.sql.failed",
                        "runtimeMs": stage_timings_ms["t2"],
                    },
                )
                blocked = SqlGenerationBlockedError(
                    stop_reason="clarification",
                    user_message=str(error),
                    detail={
                        "phase": "sql_execution",
                        "error": str(error),
                        "message": request.message,
                    },
                )
                blocked.context = context
                setattr(blocked, "stage_timings_ms", dict(stage_timings_ms))
                raise blocked from error
            stage_timings_ms["t2"] = round((perf_counter() - sql_started_at) * 1000, 2)
            sql_failures: list[str] = []
            result_failures: list[str] = []
            for index, result in enumerate(results, start=1):
                sql_pass, sql_reason = check_sql_syntax(result.sql)
                self._record_inline_check(
                    stage_id="t2",
                    check_name=f"sql_syntax_step_{index}",
                    passed=sql_pass,
                    reason=sql_reason,
                )
                if not sql_pass:
                    sql_failures.append(f"step_{index}: {sql_reason}")
                rows_pass, rows_reason = check_result_sanity(
                    result.rows,
                    result.rowCount,
                    max_rows=10_000,
                )
                self._record_inline_check(
                    stage_id="t2",
                    check_name=f"result_sanity_step_{index}",
                    passed=rows_pass,
                    reason=rows_reason,
                )
                if not rows_pass:
                    result_failures.append(f"step_{index}: {rows_reason}")
            if sql_failures or result_failures:
                blocked = SqlGenerationBlockedError(
                    stop_reason="clarification",
                    user_message="I need to refine the query plan because generated SQL failed inline safety checks.",
                    detail={
                        "phase": "inline_checks",
                        "sqlFailures": sql_failures,
                        "resultFailures": result_failures,
                    },
                )
                blocked.context = context
                setattr(blocked, "stage_timings_ms", dict(stage_timings_ms))
                raise blocked
            first_result = results[0] if results else None
            first_sql = first_result.sql if first_result else ""
            all_sql = [result.sql for result in results if result.sql]
            all_columns: set[str] = set()
            for result in results:
                if result.rows and isinstance(result.rows[0], dict):
                    all_columns.update(str(column) for column in result.rows[0].keys())
            set_stage_output(
                self._results_summary(results),
                attributes={
                    "sql.query": first_sql,
                    "sql.queries": json.dumps(all_sql, ensure_ascii=True),
                    "result.row_count": sum(result.rowCount for result in results),
                    "result.columns": ",".join(sorted(all_columns)),
                    "retry.count": len(context.sql_retry_feedback),
                    "runtime.ms": stage_timings_ms["t2"],
                },
            )
            logger.info(
                "SQL stage completed",
                extra={
                    "event": "orchestrator.pipeline.sql.completed",
                    "queryCount": len(results),
                    "totalRows": sum(result.rowCount for result in results),
                    "runtimeMs": stage_timings_ms["t2"],
                },
            )

        await progress_callback("Running numeric QA and consistency checks")
        validation_started_at = perf_counter()
        with stage_span(
            span_name="pipeline.t3_validation",
            stage_id="t3",
            input_value={
                "queryCount": len(results),
                "rowCounts": [result.rowCount for result in results],
            },
        ):
            validation = await self._dependencies.validate_results(results)
            stage_timings_ms["t3"] = round((perf_counter() - validation_started_at) * 1000, 2)
            contract_pass, contract_reason = check_validation_contract(validation.passed, validation.checks)
            self._record_inline_check(
                stage_id="t3",
                check_name="validation_contract",
                passed=contract_pass,
                reason=contract_reason,
            )
            set_stage_output(
                {"passed": validation.passed, "checks": validation.checks},
                attributes={
                    "validation.passed": validation.passed,
                    "validation.check_count": len(validation.checks),
                    "runtime.ms": stage_timings_ms["t3"],
                },
            )
            logger.info(
                "Validation completed",
                extra={
                    "event": "orchestrator.pipeline.validation.completed",
                    "passed": validation.passed,
                    "checkCount": len(validation.checks),
                    "runtimeMs": stage_timings_ms["t3"],
                },
            )

        if not validation.passed:
            logger.error(
                "Validation failed",
                extra={
                    "event": "orchestrator.pipeline.validation.failed",
                    "checks": validation.checks,
                },
            )
            raise RuntimeError("Result validation failed.")
        logger.info(
            "Pipeline execution completed",
            extra={
                "event": "orchestrator.pipeline.completed",
                "durationMs": round((perf_counter() - pipeline_started_at) * 1000, 2),
                "stageTimingsMs": stage_timings_ms,
            },
        )
        return context, results, validation, stage_timings_ms

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
            "presentationIntent": context.presentation_intent.model_dump(),
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
            "presentationIntent": response.presentationIntent.model_dump() if response.presentationIntent else None,
            "chartConfig": response.chartConfig.model_dump() if response.chartConfig else None,
            "tableConfig": response.tableConfig.model_dump() if response.tableConfig else None,
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

    def _inline_checks_for_stage(self, stage_id: str) -> list[str]:
        return list(self._latest_inline_checks.get(stage_id, []))

    def _deterministic_answer_fallback(self, response: AgentResponse) -> str:
        summary_bits: list[str] = []
        if response.summaryCards:
            for card in response.summaryCards[:3]:
                summary_bits.append(f"{card.label}: {card.value}")
        elif response.metrics:
            for metric in response.metrics[:3]:
                summary_bits.append(f"{metric.label}: {metric.value} {metric.unit}")
        elif response.dataTables:
            summary_bits.append(f"Retrieved {len(response.dataTables)} table(s) for review.")
        if not summary_bits:
            summary_bits.append("Analysis completed. Review tables and trace for details.")
        return " | ".join(summary_bits)

    def _apply_synthesis_inline_checks(self, response: AgentResponse, *, phase: str) -> AgentResponse:
        answer_pass, answer_reason = check_answer_sanity(response.answer)
        self._record_inline_check(
            stage_id="t4",
            check_name=f"answer_sanity_{phase}",
            passed=answer_pass,
            reason=answer_reason,
        )
        pii_pass, pii_reason = check_pii(response.answer)
        self._record_inline_check(
            stage_id="t4",
            check_name=f"pii_scan_{phase}",
            passed=pii_pass,
            reason=pii_reason,
        )
        if not answer_pass:
            reason_text = answer_reason.lower()
            if "error pattern" in reason_text or "empty" in reason_text:
                response.answer = self._deterministic_answer_fallback(response)
                response.assumptions = [*response.assumptions, f"Inline check fallback applied: {answer_reason}"][:5]
            elif "shorter than" in reason_text:
                # Concise answers are allowed for some deterministic/test providers.
                pass
            else:
                response.assumptions = [*response.assumptions, f"Inline check warning: {answer_reason}"][:5]
        if not pii_pass:
            response.answer = redact_pii(response.answer)
            response.assumptions = [*response.assumptions, f"Inline check redaction applied: {pii_reason}"][:5]
        return response

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

    @staticmethod
    def _provider_request_payloads(llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for entry in llm_entries:
            metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
            raw_payload = metadata.get("providerRequestPayload")
            if isinstance(raw_payload, dict):
                payloads.append(raw_payload)
        return payloads

    def _sql_retry_feedback(self, llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for entry in llm_entries:
            metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
            raw_feedback = metadata.get("retryFeedback")
            if not isinstance(raw_feedback, list):
                continue
            for item in raw_feedback:
                if not isinstance(item, dict):
                    continue
                collected.append(item)
        return normalize_retry_feedback(collected, max_items=6)

    @staticmethod
    def _warehouse_errors(retry_feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return execution_error_view(retry_feedback, max_items=6)

    @staticmethod
    def _step_runtime(stage_timings_ms: dict[str, float], step_id: str) -> float | None:
        value = stage_timings_ms.get(step_id)
        if value is None:
            return None
        return round(value, 2)

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
        stage_timings_ms: dict[str, float],
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
        provider_requests = self._provider_request_payloads(sql_llm_entries)

        return [
            TraceStep(
                id="t1",
                title="Build plan",
                summary="Generated ordered analysis plan under semantic-model policy guardrails.",
                status="done",
                runtimeMs=self._step_runtime(stage_timings_ms, "t1"),
                qualityChecks=self._inline_checks_for_stage("t1") or None,
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
                runtimeMs=self._step_runtime(stage_timings_ms, "t2"),
                sql=results[0].sql if results else None,
                qualityChecks=self._inline_checks_for_stage("t2") or None,
                stageInput={
                    "planStepIds": [step.id for step in context.plan],
                    "planGoals": [self._preview_text(step.goal, max_chars=120) for step in context.plan],
                    "historyDepth": len(prior_history),
                    "providerRequests": provider_requests,
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
                runtimeMs=self._step_runtime(stage_timings_ms, "t3"),
                qualityChecks=[*validation.checks, *self._inline_checks_for_stage("t3")],
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
                runtimeMs=self._step_runtime(stage_timings_ms, "t4"),
                qualityChecks=self._inline_checks_for_stage("t4") or None,
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
        stage_timings_ms: dict[str, float] | None = None,
    ) -> TraceStep:
        planner_llm_entries = self._llm_entries_for_stages(llm_entries, {"plan_generation"})
        resolved_timings = stage_timings_ms or {}
        return TraceStep(
            id="t1",
            title="Build plan",
            summary="Planner blocked execution and returned a guidance response.",
            status="blocked",
            runtimeMs=self._step_runtime(resolved_timings, "t1"),
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
        stage_timings_ms: dict[str, float] | None = None,
    ) -> TraceStep:
        planner_llm_entries = self._llm_entries_for_stages(llm_entries, {"plan_generation"})
        resolved_timings = stage_timings_ms or {}
        return TraceStep(
            id="t1",
            title="Build plan",
            summary="Generated ordered analysis plan under semantic-model policy guardrails.",
            status="done",
            runtimeMs=self._step_runtime(resolved_timings, "t1"),
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
        stage_timings_ms: dict[str, float] | None = None,
    ) -> TraceStep:
        sql_llm_entries = self._llm_entries_for_stages(llm_entries, {"sql_generation"})
        provider_requests = self._provider_request_payloads(sql_llm_entries)
        resolved_timings = stage_timings_ms or {}
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
            runtimeMs=self._step_runtime(resolved_timings, "t2"),
            stageInput={
                "message": request.message,
                "planStepIds": [step.id for step in context.plan],
                **self._history_summary(prior_history),
                "providerRequests": provider_requests,
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
        stage_timings_ms: dict[str, float] | None = None,
    ) -> list[TraceStep]:
        return [
            self._planner_completed_trace_step(
                request=request,
                prior_history=prior_history,
                context=context,
                llm_entries=llm_entries,
                stage_timings_ms=stage_timings_ms,
            ),
            self._sql_generation_blocked_trace_step(
                request=request,
                prior_history=prior_history,
                context=context,
                blocked=blocked,
                llm_entries=llm_entries,
                stage_timings_ms=stage_timings_ms,
            ),
        ]

    def _finalize_response(
        self,
        *,
        response: AgentResponse,
        validation: ValidationResult,
        session_depth: int,
    ) -> AgentResponse:
        _ = session_depth
        validation_step_id = "t3" if any(step.id == "t3" for step in response.trace) else "t4"
        merged_trace: list[TraceStep] = []
        for step in response.trace:
            if step.id != validation_step_id:
                merged_trace.append(step)
                continue
            existing_checks = list(step.qualityChecks or [])
            merged_checks: list[str] = []
            for check in [*existing_checks, *validation.checks, *self._inline_checks_for_stage(validation_step_id)]:
                if check not in merged_checks:
                    merged_checks.append(check)
            merged_trace.append(step.model_copy(update={"qualityChecks": merged_checks}))
        response.trace = merged_trace

        assumptions = list(response.assumptions)
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
        runtime_ms: float | None = None,
    ) -> AgentResponse:
        error_message = str(error).strip() or "Execution failed before a governed response could be produced."
        return AgentResponse(
            answer=error_message,
            confidence="low",
            whyItMatters="Execution failed before a governed response could be produced.",
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
                    runtimeMs=runtime_ms,
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

        message = blocked.user_message.strip() or "Planner blocked execution."
        return AgentResponse(
            answer=message,
            confidence="low",
            whyItMatters="Planner blocked execution until this guidance is addressed.",
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

        return AgentResponse(
            answer=blocked.user_message,
            confidence="low",
            whyItMatters="SQL generation/execution is blocked until this clarification is resolved.",
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
        started_at = perf_counter()

        async def _noop_progress(_: str) -> None:
            return None

        with bind_log_context(session_id=session_id):
            logger.info(
                "Orchestrator turn started",
                extra={
                    "event": "orchestrator.turn.started",
                    "sessionIdValue": session_id,
                    "historyDepth": len(prior_history),
                },
            )
            with turn_span(
                session_id=session_id,
                mode="sync",
                message=request.message,
                history_depth=len(prior_history),
            ):
                try:
                    with bind_llm_trace_collector(llm_collector):
                        context, results, validation, stage_timings_ms = await self._execute_pipeline(
                            request,
                            prior_history,
                            _noop_progress,
                        )
                        synthesis_started_at = perf_counter()
                        with stage_span(
                            span_name="pipeline.t4_synthesis",
                            stage_id="t4",
                            input_value={
                                "phase": "final",
                                "message": request.message,
                                "resultCount": len(results),
                                "planStepCount": len(context.plan),
                            },
                        ):
                            response = await self._dependencies.build_response(request, context, results, prior_history)
                            stage_timings_ms["t4"] = round((perf_counter() - synthesis_started_at) * 1000, 2)
                            response = self._apply_synthesis_inline_checks(response, phase="final")
                            set_stage_output(
                                self._response_summary(response),
                                attributes={
                                    "response.confidence": response.confidence,
                                    "response.table_count": len(response.dataTables),
                                    "response.artifact_count": len(response.artifacts),
                                    "runtime.ms": stage_timings_ms["t4"],
                                },
                            )
                        response.trace = self._build_trace(
                            request=request,
                            prior_history=prior_history,
                            context=context,
                            results=results,
                            validation=validation,
                            response=response,
                            phase="final",
                            llm_entries=llm_collector.entries,
                            stage_timings_ms=stage_timings_ms,
                        )
                        response = self._finalize_response(
                            response=response,
                            validation=validation,
                            session_depth=len(self._session_history.get(session_id, [])),
                        )
                except PlannerBlockedError as blocked:
                    logger.info(
                        "Orchestrator turn blocked by planner",
                        extra={
                            "event": "orchestrator.turn.blocked.planner",
                            "stopReason": blocked.stop_reason,
                            "userMessage": blocked.user_message,
                        },
                    )
                    response = self._planner_blocked_response(
                        blocked=blocked,
                        session_depth=len(self._session_history.get(session_id, [])),
                        trace_step=self._planner_blocked_trace_step(
                            request=request,
                            prior_history=prior_history,
                            blocked=blocked,
                            llm_entries=llm_collector.entries,
                            stage_timings_ms=getattr(blocked, "stage_timings_ms", {}),
                        ),
                    )
                    return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)
                except SqlGenerationBlockedError as blocked:
                    logger.info(
                        "Orchestrator turn blocked by SQL stage",
                        extra={
                            "event": "orchestrator.turn.blocked.sql",
                            "stopReason": blocked.stop_reason,
                            "userMessage": blocked.user_message,
                            "detail": blocked.detail,
                        },
                    )
                    blocked_context = getattr(blocked, "context", TurnExecutionContext(plan=[]))
                    response = self._sql_generation_blocked_response(
                        blocked=blocked,
                        session_depth=len(self._session_history.get(session_id, [])),
                        trace_steps=self._trace_until_sql_failure(
                            request=request,
                            prior_history=prior_history,
                            context=blocked_context,
                            blocked=blocked,
                            llm_entries=llm_collector.entries,
                            stage_timings_ms=getattr(blocked, "stage_timings_ms", {}),
                        ),
                    )
                    return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)
                except Exception as error:  # noqa: BLE001
                    logger.exception(
                        "Orchestrator turn failed",
                        extra={
                            "event": "orchestrator.turn.failed",
                        },
                    )
                    response = self._unexpected_failure_response(
                        request=request,
                        prior_history=prior_history,
                        llm_entries=llm_collector.entries,
                        error=error,
                        runtime_ms=round((perf_counter() - started_at) * 1000, 2),
                    )
                    return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

                logger.info(
                    "Orchestrator turn completed",
                    extra={
                        "event": "orchestrator.turn.completed",
                        "durationMs": round((perf_counter() - started_at) * 1000, 2),
                        "traceSteps": len(response.trace),
                    },
                )
                return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

    async def stream_events(self, request: ChatTurnRequest) -> AsyncIterator[dict[str, Any]]:
        session_id, prior_history = self._session_context(request)
        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        started_at = perf_counter()
        emitted_events = 0

        async def emit(event: dict[str, Any]) -> None:
            nonlocal emitted_events
            emitted_events += 1
            await event_queue.put(event)

        async def progress(message: str) -> None:
            await emit({"type": "status", "message": self._client_progress_message(message)})

        async def worker() -> None:
            llm_collector = LlmTraceCollector()
            try:
                with bind_log_context(session_id=session_id), bind_llm_trace_collector(llm_collector):
                    logger.info(
                        "Orchestrator stream started",
                        extra={
                            "event": "orchestrator.stream.started",
                            "sessionIdValue": session_id,
                            "historyDepth": len(prior_history),
                        },
                    )
                    turn_context = turn_span(
                        session_id=session_id,
                        mode="stream",
                        message=request.message,
                        history_depth=len(prior_history),
                    )
                    turn_context.__enter__()
                    try:
                        await progress("Understanding query intent and scope")
                        try:
                            context, results, validation, stage_timings_ms = await self._execute_pipeline(
                                request,
                                prior_history,
                                progress,
                            )
                        except PlannerBlockedError as blocked:
                            logger.info(
                                "Orchestrator stream blocked by planner",
                                extra={
                                    "event": "orchestrator.stream.blocked.planner",
                                    "stopReason": blocked.stop_reason,
                                },
                            )
                            await progress("Planner guardrail triggered; returning guidance response")
                            blocked_response = self._planner_blocked_response(
                                blocked=blocked,
                                session_depth=len(self._session_history.get(session_id, [])),
                                trace_step=self._planner_blocked_trace_step(
                                    request=request,
                                    prior_history=prior_history,
                                    blocked=blocked,
                                    llm_entries=llm_collector.entries,
                                    stage_timings_ms=getattr(blocked, "stage_timings_ms", {}),
                                ),
                            )
                            await emit({"type": "response", "phase": "final", "response": blocked_response.model_dump()})
                            await emit({"type": "done"})
                            return
                        except SqlGenerationBlockedError as blocked:
                            logger.info(
                                "Orchestrator stream blocked by SQL stage",
                                extra={
                                    "event": "orchestrator.stream.blocked.sql",
                                    "stopReason": blocked.stop_reason,
                                    "userMessage": blocked.user_message,
                                },
                            )
                            await progress(f"Data retrieval blocked: {blocked.user_message}")
                            blocked_context = getattr(blocked, "context", TurnExecutionContext(plan=[]))
                            blocked_response = self._sql_generation_blocked_response(
                                blocked=blocked,
                                session_depth=len(self._session_history.get(session_id, [])),
                                trace_steps=self._trace_until_sql_failure(
                                    request=request,
                                    prior_history=prior_history,
                                    context=blocked_context,
                                    blocked=blocked,
                                    llm_entries=llm_collector.entries,
                                    stage_timings_ms=getattr(blocked, "stage_timings_ms", {}),
                                ),
                            )
                            await emit({"type": "response", "phase": "final", "response": blocked_response.model_dump()})
                            await emit({"type": "done"})
                            return

                        await progress("Preparing initial answer from retrieved data")
                        fast_synthesis_started_at = perf_counter()
                        with stage_span(
                            span_name="pipeline.t4_synthesis_draft",
                            stage_id="t4",
                            input_value={
                                "phase": "draft",
                                "message": request.message,
                                "resultCount": len(results),
                                "planStepCount": len(context.plan),
                            },
                        ):
                            fast_response = await self._run_with_heartbeat(
                                operation=lambda: self._dependencies.build_fast_response(request, context, results, prior_history),
                                progress_callback=progress,
                                heartbeat_message="Building initial answer...",
                            )
                            draft_stage_timings_ms = dict(stage_timings_ms)
                            draft_stage_timings_ms["t4"] = round((perf_counter() - fast_synthesis_started_at) * 1000, 2)
                            fast_response = self._apply_synthesis_inline_checks(fast_response, phase="draft")
                            set_stage_output(
                                self._response_summary(fast_response),
                                attributes={
                                    "response.confidence": fast_response.confidence,
                                    "response.table_count": len(fast_response.dataTables),
                                    "response.artifact_count": len(fast_response.artifacts),
                                    "runtime.ms": draft_stage_timings_ms["t4"],
                                },
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
                            stage_timings_ms=draft_stage_timings_ms,
                        )
                        fast_response = self._finalize_response(
                            response=fast_response,
                            validation=validation,
                            session_depth=len(self._session_history.get(session_id, [])),
                        )
                        await emit({"type": "response", "phase": "draft", "response": fast_response.model_dump()})

                        await progress("Generating final narrative and recommendations")
                        final_synthesis_started_at = perf_counter()
                        with stage_span(
                            span_name="pipeline.t4_synthesis_final",
                            stage_id="t4",
                            input_value={
                                "phase": "final",
                                "message": request.message,
                                "resultCount": len(results),
                                "planStepCount": len(context.plan),
                            },
                        ):
                            final_response = await self._run_with_heartbeat(
                                operation=lambda: self._dependencies.build_response(request, context, results, prior_history),
                                progress_callback=progress,
                                heartbeat_message="Synthesizing narrative...",
                            )
                            final_stage_timings_ms = dict(stage_timings_ms)
                            final_stage_timings_ms["t4"] = round((perf_counter() - final_synthesis_started_at) * 1000, 2)
                            final_response = self._apply_synthesis_inline_checks(final_response, phase="final")
                            set_stage_output(
                                self._response_summary(final_response),
                                attributes={
                                    "response.confidence": final_response.confidence,
                                    "response.table_count": len(final_response.dataTables),
                                    "response.artifact_count": len(final_response.artifacts),
                                    "runtime.ms": final_stage_timings_ms["t4"],
                                },
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
                            stage_timings_ms=final_stage_timings_ms,
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
                    finally:
                        turn_context.__exit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Orchestrator stream failed",
                    extra={
                        "event": "orchestrator.stream.failed",
                    },
                )
                failure_response = self._unexpected_failure_response(
                    request=request,
                    prior_history=prior_history,
                    llm_entries=llm_collector.entries,
                    error=error,
                    runtime_ms=round((perf_counter() - started_at) * 1000, 2),
                )
                await emit({"type": "response", "phase": "final", "response": failure_response.model_dump()})
                await emit({"type": "done"})
            finally:
                logger.info(
                    "Orchestrator stream finished",
                    extra={
                        "event": "orchestrator.stream.finished",
                        "durationMs": round((perf_counter() - started_at) * 1000, 2),
                        "eventsEmitted": emitted_events,
                    },
                )
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
        started_at = perf_counter()

        async for event in self.stream_events(request):
            events.append(event)
            if event.get("type") == "response":
                response_payload = event.get("response")
                if isinstance(response_payload, dict):
                    final_response = AgentResponse.model_validate(response_payload)

        if final_response is None:
            logger.error(
                "Streaming run ended without a response",
                extra={
                    "event": "orchestrator.run_stream.missing_response",
                },
            )
            raise RuntimeError("Streaming ended before a response payload was produced.")

        logger.info(
            "Streaming run completed",
            extra={
                "event": "orchestrator.run_stream.completed",
                "eventCount": len(events),
                "durationMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return StreamResult(
            events=events,
            turn=TurnResult(
                turnId=str(uuid4()),
                createdAt=now_iso(),
                response=final_response,
            ),
        )
