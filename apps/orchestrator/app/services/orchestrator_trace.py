from __future__ import annotations

from typing import Any

from app.models import (
    AgentResponse,
    ChatTurnRequest,
    SqlExecutionResult,
    TraceStep,
    ValidationResult,
)
from app.services.llm_trace import LlmTraceEntry
from app.services.orchestrator_summaries import history_summary, plan_summary, preview_text, response_summary, results_summary
from app.services.stages import PlannerBlockedError, SqlGenerationBlockedError
from app.services.stages.sql_state_machine import execution_error_view, normalize_retry_feedback
from app.services.types import TurnExecutionContext


def llm_entries_for_stages(llm_entries: list[LlmTraceEntry], stage_names: set[str]) -> list[LlmTraceEntry]:
    return [entry for entry in llm_entries if entry.stage in stage_names]


def human_response_for_trace_entry(entry: LlmTraceEntry) -> str | None:
    if entry.error:
        return entry.error.strip() or None

    payload = entry.parsed_response if isinstance(entry.parsed_response, dict) else None
    if not payload:
        return None

    candidates = [
        payload.get("answer"),
        payload.get("lightResponse"),
        payload.get("explanation"),
        payload.get("userMessage"),
        payload.get("relevanceReason"),
        payload.get("rationale"),
        payload.get("clarificationQuestion"),
        payload.get("notRelevantReason"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()

    generation_type = payload.get("generationType") or payload.get("type")
    if isinstance(generation_type, str) and generation_type.strip():
        assumptions = payload.get("assumptions")
        assumption_suffix = ""
        if isinstance(assumptions, list):
            cleaned = [item.strip() for item in assumptions if isinstance(item, str) and item.strip()]
            if cleaned:
                assumption_suffix = f" Assumptions: {'; '.join(cleaned[:2])}."
        return f"{generation_type.strip()}.{assumption_suffix}".strip()

    return None


def llm_prompt_payload(llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
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


def llm_response_payload(llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
    return [
        {
            "provider": entry.provider,
            "metadata": entry.metadata,
            "humanResponse": human_response_for_trace_entry(entry),
            "rawResponse": entry.raw_response,
            "parsedResponse": entry.parsed_response,
            "error": entry.error,
        }
        for entry in llm_entries
    ]


def provider_request_payloads(llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for entry in llm_entries:
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        raw_payload = metadata.get("providerRequestPayload")
        if isinstance(raw_payload, dict):
            payloads.append(raw_payload)
    return payloads


def sql_retry_feedback(llm_entries: list[LlmTraceEntry]) -> list[dict[str, Any]]:
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


def warehouse_errors(retry_feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return execution_error_view(retry_feedback, max_items=6)


def step_runtime(stage_timings_ms: dict[str, float], step_id: str) -> float | None:
    value = stage_timings_ms.get(step_id)
    if value is None:
        return None
    return round(value, 2)


def build_trace(
    *,
    request: ChatTurnRequest,
    prior_history: list[str],
    context: TurnExecutionContext,
    results: list[SqlExecutionResult],
    validation: ValidationResult,
    response: AgentResponse,
    llm_entries: list[LlmTraceEntry],
    stage_timings_ms: dict[str, float],
    inline_checks_by_stage: dict[str, list[str]],
) -> list[TraceStep]:
    result_summary = results_summary(results)
    synthesis_summary = "Synthesized final narrative and recommendations from governed execution context."
    plan_llm_entries = llm_entries_for_stages(llm_entries, {"plan_generation"})
    sql_llm_entries = llm_entries_for_stages(llm_entries, {"sql_generation"})
    synthesis_llm_entries = llm_entries_for_stages(llm_entries, {"synthesis_final"})
    retry_feedback = context.sql_retry_feedback or sql_retry_feedback(sql_llm_entries)
    execution_errors = warehouse_errors(retry_feedback)
    provider_requests = provider_request_payloads(sql_llm_entries)

    return [
        TraceStep(
            id="t1",
            title="Build plan",
            summary="Generated ordered analysis plan under semantic-model policy guardrails.",
            status="done",
            runtimeMs=step_runtime(stage_timings_ms, "t1"),
            qualityChecks=list(inline_checks_by_stage.get("t1", [])) or None,
            stageInput={
                "message": request.message,
                **history_summary(prior_history),
                "llmPrompts": llm_prompt_payload(plan_llm_entries),
            },
            stageOutput={
                **plan_summary(context),
                "llmResponses": llm_response_payload(plan_llm_entries),
            },
        ),
        TraceStep(
            id="t2",
            title="Generate and execute SQL",
            summary="Generated governed SQL for each plan step and executed against the analytics provider.",
            status="done",
            runtimeMs=step_runtime(stage_timings_ms, "t2"),
            sql=results[0].sql if results else None,
            qualityChecks=list(inline_checks_by_stage.get("t2", [])) or None,
            stageInput={
                "planStepIds": [step.id for step in context.plan],
                "planGoals": [preview_text(step.goal, max_chars=120) for step in context.plan],
                "historyDepth": len(prior_history),
                "providerRequests": provider_requests,
                "llmPrompts": llm_prompt_payload(sql_llm_entries),
            },
            stageOutput={
                **result_summary,
                "interpretationNotes": context.sql_interpretation_notes,
                "caveats": context.sql_caveats,
                "executionNotes": context.sql_assumptions,
                "retryFeedback": retry_feedback,
                "warehouseErrors": execution_errors,
                "llmResponses": llm_response_payload(sql_llm_entries),
            },
        ),
        TraceStep(
            id="t3",
            title="Validate results",
            summary="Applied numeric and policy quality checks to ensure returned tables are usable.",
            status="done" if validation.passed else "blocked",
            runtimeMs=step_runtime(stage_timings_ms, "t3"),
            qualityChecks=[*validation.checks, *inline_checks_by_stage.get("t3", [])],
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
            runtimeMs=step_runtime(stage_timings_ms, "t4"),
            qualityChecks=list(inline_checks_by_stage.get("t4", [])) or None,
            stageInput={
                "sqlInterpretationNoteCount": len(context.sql_interpretation_notes),
                "sqlCaveatCount": len(context.sql_caveats),
                "sqlAssumptionCount": len(context.sql_assumptions),
                "resultSummary": result_summary,
                "llmPrompts": llm_prompt_payload(synthesis_llm_entries),
            },
            stageOutput={
                **response_summary(response),
                "llmResponses": llm_response_payload(synthesis_llm_entries),
            },
        ),
    ]


def planner_blocked_trace_step(
    *,
    request: ChatTurnRequest,
    prior_history: list[str],
    blocked: PlannerBlockedError,
    llm_entries: list[LlmTraceEntry],
    stage_timings_ms: dict[str, float] | None = None,
) -> TraceStep:
    planner_llm_entries = llm_entries_for_stages(llm_entries, {"plan_generation"})
    resolved_timings = stage_timings_ms or {}
    return TraceStep(
        id="t1",
        title="Build plan",
        summary="Planner blocked execution and returned a guidance response.",
        status="blocked",
        runtimeMs=step_runtime(resolved_timings, "t1"),
        stageInput={
            "message": request.message,
            **history_summary(prior_history),
            "llmPrompts": llm_prompt_payload(planner_llm_entries),
        },
        stageOutput={
            "stopReason": blocked.stop_reason,
            "userMessage": blocked.user_message,
            "llmResponses": llm_response_payload(planner_llm_entries),
        },
    )


def planner_completed_trace_step(
    *,
    request: ChatTurnRequest,
    prior_history: list[str],
    context: TurnExecutionContext,
    llm_entries: list[LlmTraceEntry],
    stage_timings_ms: dict[str, float] | None = None,
) -> TraceStep:
    planner_llm_entries = llm_entries_for_stages(llm_entries, {"plan_generation"})
    resolved_timings = stage_timings_ms or {}
    return TraceStep(
        id="t1",
        title="Build plan",
        summary="Generated ordered analysis plan under semantic-model policy guardrails.",
        status="done",
        runtimeMs=step_runtime(resolved_timings, "t1"),
        stageInput={
            "message": request.message,
            **history_summary(prior_history),
            "llmPrompts": llm_prompt_payload(planner_llm_entries),
        },
        stageOutput={
            **plan_summary(context),
            "llmResponses": llm_response_payload(planner_llm_entries),
        },
    )


def sql_generation_blocked_trace_step(
    *,
    request: ChatTurnRequest,
    prior_history: list[str],
    context: TurnExecutionContext,
    blocked: SqlGenerationBlockedError,
    llm_entries: list[LlmTraceEntry],
    stage_timings_ms: dict[str, float] | None = None,
) -> TraceStep:
    sql_llm_entries = llm_entries_for_stages(llm_entries, {"sql_generation"})
    requests = provider_request_payloads(sql_llm_entries)
    resolved_timings = stage_timings_ms or {}
    detail_retry_feedback = blocked.detail.get("retryFeedback") if blocked.detail else None
    if isinstance(detail_retry_feedback, list):
        retry_feedback = [item for item in detail_retry_feedback if isinstance(item, dict)]
    else:
        retry_feedback = context.sql_retry_feedback or sql_retry_feedback(sql_llm_entries)
    stage_output: dict[str, Any] = {
        "stopReason": blocked.stop_reason,
        "userMessage": blocked.user_message,
        "retryFeedback": retry_feedback,
        "warehouseErrors": warehouse_errors(retry_feedback),
        "llmResponses": llm_response_payload(sql_llm_entries),
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
        runtimeMs=step_runtime(resolved_timings, "t2"),
        stageInput={
            "message": request.message,
            "planStepIds": [step.id for step in context.plan],
            **history_summary(prior_history),
            "providerRequests": requests,
            "llmPrompts": llm_prompt_payload(sql_llm_entries),
        },
        stageOutput=stage_output,
    )


def trace_until_sql_failure(
    *,
    request: ChatTurnRequest,
    prior_history: list[str],
    context: TurnExecutionContext,
    blocked: SqlGenerationBlockedError,
    llm_entries: list[LlmTraceEntry],
    stage_timings_ms: dict[str, float] | None = None,
) -> list[TraceStep]:
    return [
        planner_completed_trace_step(
            request=request,
            prior_history=prior_history,
            context=context,
            llm_entries=llm_entries,
            stage_timings_ms=stage_timings_ms,
        ),
        sql_generation_blocked_trace_step(
            request=request,
            prior_history=prior_history,
            context=context,
            blocked=blocked,
            llm_entries=llm_entries,
            stage_timings_ms=stage_timings_ms,
        ),
    ]
