from __future__ import annotations

from enum import Enum
from typing import Any

from app.services.stages.sql_stage_models import GeneratedStep


class SqlFailureCode(str, Enum):
    USER_INPUT_REQUIRED = "user_input_required"
    NOT_RELEVANT = "not_relevant"
    GENERATION_EMPTY_SQL = "generation_empty_sql"
    GENERATION_MALFORMED_PAYLOAD = "generation_malformed_payload"
    GENERATION_GUARDRAIL_REJECTED = "generation_guardrail_rejected"
    GENERATION_PROVIDER_ERROR = "generation_provider_error"
    EXECUTION_WAREHOUSE_ERROR = "execution_warehouse_error"
    EXECUTION_ALL_NULL_ROWS = "execution_all_null_rows"
    RETRY_LIMIT_EXHAUSTED = "retry_limit_exhausted"
    TOO_COMPLEX = "too_complex"


def error_category(code: SqlFailureCode) -> str:
    if code in {SqlFailureCode.USER_INPUT_REQUIRED, SqlFailureCode.NOT_RELEVANT, SqlFailureCode.TOO_COMPLEX}:
        return "user"
    if code in {SqlFailureCode.EXECUTION_WAREHOUSE_ERROR, SqlFailureCode.EXECUTION_ALL_NULL_ROWS}:
        return "execution"
    return "generation"


def failure_code_for_generated(generated: GeneratedStep) -> SqlFailureCode:
    if generated.status == "not_relevant":
        return SqlFailureCode.NOT_RELEVANT
    if generated.status != "clarification":
        return SqlFailureCode.GENERATION_MALFORMED_PAYLOAD

    if generated.clarification_kind == "technical_failure":
        return SqlFailureCode.GENERATION_PROVIDER_ERROR

    return SqlFailureCode.USER_INPUT_REQUIRED


def build_retry_event(
    *,
    code: SqlFailureCode,
    step_id: str,
    attempt: int,
    provider: str,
    error: str,
    failed_sql: str | None,
    clarification_question: str = "",
    clarification_kind: str = "",
    not_relevant_reason: str = "",
) -> dict[str, Any]:
    phase = "sql_execution" if error_category(code) == "execution" else "sql_generation"
    payload: dict[str, Any] = {
        "phase": phase,
        "stepId": step_id,
        "attempt": attempt,
        "provider": provider,
        "errorCode": code.value,
        "errorCategory": error_category(code),
        "error": str(error or "").strip(),
        "failedSql": failed_sql or None,
    }
    if clarification_question:
        payload["clarificationQuestion"] = clarification_question
    if clarification_kind:
        payload["clarificationKind"] = clarification_kind
    if not_relevant_reason:
        payload["notRelevantReason"] = not_relevant_reason
    return payload


def normalize_retry_feedback(entries: list[dict[str, Any]], *, max_items: int = 12) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        phase = str(item.get("phase", "")).strip()
        raw_error_code = str(item.get("errorCode", "")).strip()
        error_category_value = str(item.get("errorCategory", "")).strip()
        raw_failed_sql = item.get("failedSql")
        failed_sql_value: str | None = None
        if isinstance(raw_failed_sql, str):
            normalized_failed_sql = raw_failed_sql.strip()
            if normalized_failed_sql and normalized_failed_sql.lower() != "none":
                failed_sql_value = normalized_failed_sql

        payload: dict[str, Any] = {
            "phase": phase,
            "stepId": str(item.get("stepId", "")).strip(),
            "attempt": int(item.get("attempt", 0) or 0),
            "provider": str(item.get("provider", "")).strip(),
            "errorCode": raw_error_code,
            "errorCategory": error_category_value,
            "error": str(item.get("error", "")).strip(),
            "failedSql": failed_sql_value,
        }
        clarification_q = str(item.get("clarificationQuestion", "")).strip()
        if clarification_q:
            payload["clarificationQuestion"] = clarification_q
        clarification_kind = str(item.get("clarificationKind", "")).strip()
        if clarification_kind:
            payload["clarificationKind"] = clarification_kind
        not_relevant_reason = str(item.get("notRelevantReason", "")).strip()
        if not_relevant_reason:
            payload["notRelevantReason"] = not_relevant_reason
        key = str(payload)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(payload)
    return normalized[-max_items:]


def informed_clarification_message(
    *,
    step_goal: str,
    clarification_question: str,
    clarification_kind: str,
    retry_feedback: list[dict[str, Any]],
    max_attempts: int,
    fallback_error: str = "",
) -> str:
    question = str(clarification_question or "").strip()
    if clarification_kind == "user_input_required" and question:
        return question if question.endswith("?") else f"{question}?"

    normalized = normalize_retry_feedback(retry_feedback, max_items=8)
    execution_events = [
        item
        for item in normalized
        if str(item.get("phase", "")).strip() == "sql_execution"
        or str(item.get("errorCategory", "")).strip() == "execution"
    ]
    if execution_events:
        latest = execution_events[-1]
        attempt_count = max(int(item.get("attempt", 0) or 0) for item in execution_events)
        attempt_count = max(1, min(attempt_count, max_attempts))
        latest_code = str(latest.get("errorCode", "")).strip() or SqlFailureCode.EXECUTION_WAREHOUSE_ERROR.value
        return f"SQL execution failed ({latest_code}) after {attempt_count} attempt(s)."

    if clarification_kind == "technical_failure":
        generation_events = [
            item
            for item in normalized
            if str(item.get("phase", "")).strip() == "sql_generation"
            or str(item.get("errorCategory", "")).strip() == "generation"
        ]
        latest_generation = generation_events[-1] if generation_events else {}
        generation_code = (
            str(latest_generation.get("errorCode", "")).strip()
            or SqlFailureCode.GENERATION_PROVIDER_ERROR.value
        )
        return f"SQL generation failed ({generation_code})."

    if question:
        if question.endswith("?"):
            return question
        if question.endswith("."):
            return question
        return f"{question}."

    return f"SQL generation failed ({SqlFailureCode.GENERATION_PROVIDER_ERROR.value})."


def execution_error_view(retry_feedback: list[dict[str, Any]], *, max_items: int = 6) -> list[dict[str, Any]]:
    normalized = normalize_retry_feedback(retry_feedback, max_items=max_items * 2)
    filtered = [
        item
        for item in normalized
        if str(item.get("errorCategory", "")).strip() == "execution"
        or str(item.get("phase", "")).strip() == "sql_execution"
    ]
    return filtered[-max_items:]
