from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Literal

from app.config import settings
from app.models import QueryPlanStep
from app.prompts.templates import sql_prompt
from app.services.llm_json import as_string_list
from app.services.llm_trace import llm_trace_stage, record_llm_trace
from app.services.llm_schemas import AnalystResponsePayload
from app.services.semantic_policy import SemanticPolicy, load_semantic_policy
from app.services.sql_guardrails import guard_sql
from app.services.stages.sql_stage_models import GeneratedStep

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)
ClarificationKind = Literal["none", "user_input_required", "technical_failure"]


class AnalystGenerationError(RuntimeError):
    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def _compact_text(value: Any, *, max_chars: int = 800) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


def _provider_error_detail(error: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "errorType": type(error).__name__,
        "message": _compact_text(str(error), max_chars=1200),
    }
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        payload["statusCode"] = status_code
    raw_detail = getattr(error, "detail", None)
    if isinstance(raw_detail, dict):
        payload["providerDetail"] = raw_detail
    elif raw_detail is not None:
        payload["providerDetail"] = _compact_text(raw_detail, max_chars=1200)
    response_text = getattr(error, "response_text", None)
    if isinstance(response_text, str) and response_text.strip():
        payload["responseTextPreview"] = _compact_text(response_text, max_chars=1200)
    return payload


def _normalize_generation_type(raw_type: Any) -> Literal["sql_ready", "clarification", "not_relevant"]:
    normalized = str(raw_type or "").strip().lower().replace("-", "_")
    if normalized in {"sql_ready", "answer", "sql"}:
        return "sql_ready"
    if normalized in {"clarification", "clarify"}:
        return "clarification"
    if normalized in {"not_relevant", "out_of_domain", "irrelevant"}:
        return "not_relevant"
    return "sql_ready"


def _clean_assumptions(assumptions: list[str], *, clarification_question: str) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    question_key = " ".join(str(clarification_question or "").split()).strip().lower()
    for item in assumptions:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        key = text.lower()
        if question_key and key == question_key:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped[:4]


def _normalize_clarification_kind(raw_kind: Any) -> ClarificationKind:
    normalized = str(raw_kind or "").strip().lower().replace("-", "_")
    if normalized in {"user_input_required", "technical_failure"}:
        return normalized
    return "none"


def _infer_clarification_kind(
    *,
    status: Literal["sql_ready", "clarification", "not_relevant"],
    raw_kind: Any,
    clarification_question: str,
    attempted_sql: str | None,
) -> ClarificationKind:
    if status != "clarification":
        return "none"

    normalized_kind = _normalize_clarification_kind(raw_kind)
    if normalized_kind != "none":
        return normalized_kind

    if clarification_question:
        return "user_input_required"
    if attempted_sql and attempted_sql.strip():
        return "technical_failure"
    return "none"


class SqlStepGenerator:
    def __init__(
        self,
        *,
        ask_llm_json: AskLlmJsonFn,
        analyst_fn: AnalystFn | None = None,
        policy: SemanticPolicy | None = None,
    ) -> None:
        self._ask_llm_json = ask_llm_json
        self._analyst_fn = analyst_fn
        self._policy = policy or load_semantic_policy()

    async def _generate_with_analyst(
        self,
        *,
        message: str,
        step: QueryPlanStep,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None,
        temporal_scope: dict[str, Any] | None,
        dependency_context: list[dict[str, Any]] | None,
    ) -> GeneratedStep:
        if self._analyst_fn is None:
            raise RuntimeError("Analyst provider is not configured.")

        analyst_history = list(history)
        if temporal_scope:
            analyst_history.append(f"Planner temporal scope contract: {json.dumps(temporal_scope, ensure_ascii=True)}")
        if dependency_context:
            analyst_history.append(
                "Dependency context from completed prerequisite steps: "
                f"{json.dumps(dependency_context, ensure_ascii=True)}"
            )

        analyst_request = {
            "conversation_id": f"{conversation_id}::sub::{step.id}",
            "message": step.goal,
            "history": analyst_history,
            "step_id": step.id,
            "retry_feedback": retry_feedback or [],
            "dependency_context": dependency_context or [],
        }
        analyst_trace_system, analyst_trace_user = sql_prompt(
            message,
            step.id,
            step.goal,
            prior_sql,
            history,
            retry_feedback=retry_feedback,
            temporal_scope=temporal_scope,
            dependency_context=dependency_context,
        )

        with llm_trace_stage(
            "sql_generation",
            {
                "provider": "analyst",
                "providerMode": settings.provider_mode,
                "analystTarget": (
                    "sandbox_cortex_emulator"
                    if settings.provider_mode in {"sandbox", "prod-sandbox"}
                    else "snowflake_cortex_analyst"
                ),
                "stepId": step.id,
                "stepGoal": step.goal,
                "attempt": attempt_number,
                "retryFeedbackCount": len(retry_feedback or []),
                "retryFeedback": (retry_feedback or [])[-2:],
            },
        ):
            try:
                analyst_payload_raw = await self._analyst_fn(
                    conversation_id=str(analyst_request["conversation_id"]),
                    message=str(analyst_request["message"]),
                    history=analyst_history,
                    step_id=step.id,
                    retry_feedback=retry_feedback or [],
                    dependency_context=dependency_context,
                )
            except Exception as error:  # noqa: BLE001
                provider_error = _provider_error_detail(error)
                record_llm_trace(
                    provider="analyst",
                    system_prompt=analyst_trace_system,
                    user_prompt=analyst_trace_user,
                    max_tokens=None,
                    temperature=None,
                    raw_response=None,
                    parsed_response=None,
                    error=str(error),
                    metadata={
                        "providerRequestPayload": analyst_request,
                        "providerError": provider_error,
                    },
                )
                raise AnalystGenerationError(
                    "Analyst provider request failed.",
                    detail=provider_error,
                ) from error
            analyst_raw_text = json.dumps(analyst_payload_raw, ensure_ascii=True)
            try:
                analyst_payload_model = AnalystResponsePayload.model_validate(analyst_payload_raw)
                analyst_payload = analyst_payload_model.model_dump(mode="json", exclude_none=True)
                record_llm_trace(
                    provider="analyst",
                    system_prompt=analyst_trace_system,
                    user_prompt=analyst_trace_user,
                    max_tokens=None,
                    temperature=None,
                    raw_response=analyst_raw_text,
                    parsed_response=analyst_payload,
                    metadata={"providerRequestPayload": analyst_request},
                )
            except Exception as error:  # noqa: BLE001
                record_llm_trace(
                    provider="analyst",
                    system_prompt=analyst_trace_system,
                    user_prompt=analyst_trace_user,
                    max_tokens=None,
                    temperature=None,
                    raw_response=analyst_raw_text,
                    parsed_response=analyst_payload_raw if isinstance(analyst_payload_raw, dict) else None,
                    error=str(error),
                    metadata={"providerRequestPayload": analyst_request},
                )
                raise AnalystGenerationError(
                    "Analyst response schema validation failed.",
                    detail={
                        "errorType": type(error).__name__,
                        "message": _compact_text(str(error), max_chars=1200),
                        "providerPayload": analyst_payload_raw if isinstance(analyst_payload_raw, dict) else None,
                    },
                ) from error

        generation_type = _normalize_generation_type(analyst_payload.get("type"))
        clarification_question = str(analyst_payload.get("clarificationQuestion", "")).strip()
        not_relevant_reason = str(analyst_payload.get("notRelevantReason", "")).strip()
        if clarification_question:
            generation_type = "clarification"
        if generation_type == "sql_ready" and str(analyst_payload.get("relevance", "")).strip().lower() == "out_of_domain":
            generation_type = "not_relevant"
            if not not_relevant_reason:
                not_relevant_reason = str(analyst_payload.get("relevanceReason", "")).strip()

        candidate_sql = str(analyst_payload.get("sql", "")).strip()
        raw_failed_sql = analyst_payload.get("failedSql")
        attempted_sql = raw_failed_sql.strip() if isinstance(raw_failed_sql, str) else ""
        attempted_sql = attempted_sql or candidate_sql
        rationale = str(analyst_payload.get("lightResponse", "") or analyst_payload.get("explanation", "")).strip()
        interpretation_notes = as_string_list(analyst_payload.get("interpretationNotes"), max_items=2)
        caveats = as_string_list(analyst_payload.get("caveats"), max_items=4)
        assumptions = as_string_list(analyst_payload.get("assumptions"), max_items=4)
        payload_rows = None
        clarification_kind = _infer_clarification_kind(
            status=generation_type,
            raw_kind=analyst_payload.get("clarificationKind"),
            clarification_question=clarification_question,
            attempted_sql=attempted_sql,
        )
        if generation_type == "clarification" and clarification_kind == "technical_failure":
            detail = clarification_question or rationale or "Analyst returned a technical SQL generation failure."
            raise AnalystGenerationError(
                detail,
                detail={
                    "errorType": "AnalystTechnicalFailure",
                    "generationType": generation_type,
                    "clarificationKind": clarification_kind,
                    "providerPayload": analyst_payload,
                },
            )
        if generation_type == "sql_ready" and not candidate_sql:
            raise AnalystGenerationError(
                "SQL generation failed: analyst returned sql_ready without executable SQL.",
                detail={
                    "errorType": "AnalystMalformedPayload",
                    "generationType": generation_type,
                    "providerPayload": analyst_payload,
                },
            )

        guarded_sql = None
        if generation_type == "sql_ready" and candidate_sql:
            try:
                guarded_sql = guard_sql(candidate_sql, self._policy)
            except Exception as error:  # noqa: BLE001
                raise AnalystGenerationError(
                    f"SQL guardrail validation failed for step {step.id}: {error}",
                    detail={
                        "errorType": type(error).__name__,
                        "message": _compact_text(str(error), max_chars=1200),
                        "generationType": generation_type,
                        "sqlPreview": _compact_text(candidate_sql, max_chars=800),
                    },
                ) from error
        if generation_type == "sql_ready" and not guarded_sql:
            raise AnalystGenerationError(
                f"SQL generation returned no executable SQL for step {step.id}.",
                detail={
                    "errorType": "AnalystEmptySqlAfterGuard",
                    "generationType": generation_type,
                    "providerPayload": analyst_payload,
                },
            )
        interpretation_notes = _clean_assumptions(interpretation_notes, clarification_question=clarification_question)
        caveats = _clean_assumptions(caveats, clarification_question=clarification_question)
        assumptions = _clean_assumptions(assumptions, clarification_question=clarification_question)

        return GeneratedStep(
            index=-1,
            step=step,
            provider="analyst",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            interpretation_notes=interpretation_notes,
            caveats=caveats,
            assumptions=assumptions,
            clarification_question=clarification_question,
            not_relevant_reason=not_relevant_reason,
            clarification_kind=clarification_kind,
            attempted_sql=attempted_sql or None,
            rows=payload_rows,
        )

    async def _generate_with_llm(
        self,
        *,
        message: str,
        step: QueryPlanStep,
        history: list[str],
        prior_sql: list[str],
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None,
        temporal_scope: dict[str, Any] | None,
        dependency_context: list[dict[str, Any]] | None,
    ) -> GeneratedStep:
        sql_text = ""
        rationale = ""
        clarification_question = ""
        not_relevant_reason = ""
        clarification_kind: ClarificationKind = "none"
        interpretation_notes: list[str] = []
        caveats: list[str] = []
        assumptions: list[str] = []
        generation_type: Literal["sql_ready", "clarification", "not_relevant"] = "sql_ready"
        attempted_sql: str | None = None

        try:
            system_prompt, user_prompt = sql_prompt(
                message,
                step.id,
                step.goal,
                prior_sql,
                history,
                retry_feedback=retry_feedback,
                temporal_scope=temporal_scope,
                dependency_context=dependency_context,
            )
            with llm_trace_stage(
                "sql_generation",
                {
                    "provider": "llm",
                    "stepId": step.id,
                    "stepGoal": step.goal,
                    "historyDepth": len(history),
                    "priorSqlCount": len(prior_sql),
                    "attempt": attempt_number,
                    "retryFeedbackCount": len(retry_feedback or []),
                    "retryFeedback": (retry_feedback or [])[-2:],
                },
            ):
                payload = await self._ask_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=min(settings.real_llm_max_tokens, 1100),
                )
            generation_type = _normalize_generation_type(payload.get("generationType", payload.get("type")))
            clarification_question = str(payload.get("clarificationQuestion", "")).strip()
            not_relevant_reason = str(payload.get("notRelevantReason", "")).strip()
            rationale = str(payload.get("rationale", "")).strip()
            candidate_sql = str(payload.get("sql", "")).strip()
            attempted_sql = candidate_sql or attempted_sql
            interpretation_notes.extend(as_string_list(payload.get("interpretationNotes"), max_items=2))
            caveats.extend(as_string_list(payload.get("caveats"), max_items=4))
            assumptions.extend(as_string_list(payload.get("assumptions"), max_items=4))
            clarification_kind = _infer_clarification_kind(
                status=generation_type,
                raw_kind=payload.get("clarificationKind"),
                clarification_question=clarification_question,
                attempted_sql=attempted_sql,
            )

            if generation_type == "clarification":
                if not clarification_question:
                    raise RuntimeError(
                        f"SQL generation returned clarification without clarificationQuestion for step {step.id}."
                    )
                candidate_sql = ""
            elif generation_type == "not_relevant":
                candidate_sql = ""
            elif candidate_sql:
                sql_text = candidate_sql
        except Exception as error:
            logger.exception(
                "LLM SQL generation failed",
                extra={
                    "event": "sql.generation.llm_failed",
                    "stepId": step.id,
                    "attempt": attempt_number,
                },
            )
            generation_type = "clarification"
            clarification_kind = "technical_failure"
            clarification_question = str(error).strip()
            caveats.append(f"SQL generation failed: {error}")

        guarded_sql = None
        if generation_type == "sql_ready":
            try:
                guarded_sql = guard_sql(sql_text, self._policy)
            except Exception as error:  # noqa: BLE001
                generation_type = "clarification"
                clarification_kind = "technical_failure"
                caveats.append(f"SQL generation guardrail check failed: {error}")
                clarification_question = (
                    clarification_question
                    or rationale
                    or str(error).strip()
                )
        if generation_type == "sql_ready" and not guarded_sql:
            generation_type = "clarification"
            clarification_kind = "technical_failure"
            clarification_question = (
                clarification_question
                or rationale
                or ""
            )
        interpretation_notes = _clean_assumptions(interpretation_notes, clarification_question=clarification_question)
        caveats = _clean_assumptions(caveats, clarification_question=clarification_question)
        assumptions = _clean_assumptions(assumptions, clarification_question=clarification_question)

        return GeneratedStep(
            index=-1,
            step=step,
            provider="llm",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            interpretation_notes=interpretation_notes,
            caveats=caveats,
            assumptions=assumptions,
            clarification_question=clarification_question,
            not_relevant_reason=not_relevant_reason,
            clarification_kind=clarification_kind,
            attempted_sql=attempted_sql,
            rows=None,
        )

    async def generate(
        self,
        *,
        index: int,
        message: str,
        step: QueryPlanStep,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None = None,
        temporal_scope: dict[str, Any] | None = None,
        dependency_context: list[dict[str, Any]] | None = None,
    ) -> GeneratedStep:
        generated: GeneratedStep
        if self._analyst_fn is not None:
            try:
                generated = await self._generate_with_analyst(
                    message=message,
                    step=step,
                    history=history,
                    prior_sql=prior_sql,
                    conversation_id=conversation_id,
                    attempt_number=attempt_number,
                    retry_feedback=retry_feedback,
                    temporal_scope=temporal_scope,
                    dependency_context=dependency_context,
                )
            except Exception as error:
                logger.exception(
                    "Analyst SQL generation failed",
                    extra={
                        "event": "sql.generation.analyst_failed",
                        "stepId": step.id,
                        "attempt": attempt_number,
                    },
                )
                error_detail = (
                    dict(error.detail)
                    if isinstance(error, AnalystGenerationError) and isinstance(error.detail, dict)
                    else _provider_error_detail(error)
                )
                provider_detail = error_detail.get("providerDetail")
                provider_code = ""
                if isinstance(provider_detail, dict):
                    provider_code = str(provider_detail.get("code", "")).strip()
                error_code = provider_code or str(error_detail.get("errorType", "")).strip() or "generation_provider_error"
                error_type = str(error_detail.get("errorType", "")).strip()
                should_fallback_to_llm = (
                    settings.provider_mode == "sandbox" and error_type != "AnalystTechnicalFailure"
                )

                if should_fallback_to_llm:
                    logger.warning(
                        "Falling back to direct LLM SQL generation after sandbox analyst failure",
                        extra={
                            "event": "sql.generation.analyst_fallback_to_llm",
                            "stepId": step.id,
                            "attempt": attempt_number,
                            "errorCode": error_code,
                        },
                    )
                    try:
                        fallback_generated = await self._generate_with_llm(
                            message=message,
                            step=step,
                            history=history,
                            prior_sql=prior_sql,
                            attempt_number=attempt_number,
                            retry_feedback=retry_feedback,
                            temporal_scope=temporal_scope,
                            dependency_context=dependency_context,
                        )
                        fallback_assumptions = _clean_assumptions(
                            fallback_generated.assumptions,
                            clarification_question=fallback_generated.clarification_question,
                        )
                        generated = GeneratedStep(
                            index=index,
                            step=fallback_generated.step,
                            provider=fallback_generated.provider,
                            status=fallback_generated.status,
                            sql=fallback_generated.sql,
                            rationale=fallback_generated.rationale,
                            interpretation_notes=fallback_generated.interpretation_notes,
                            caveats=fallback_generated.caveats,
                            assumptions=fallback_assumptions,
                            clarification_question=fallback_generated.clarification_question,
                            not_relevant_reason=fallback_generated.not_relevant_reason,
                            clarification_kind=fallback_generated.clarification_kind,
                            attempted_sql=fallback_generated.attempted_sql,
                            rows=fallback_generated.rows,
                            generation_error_detail=error_detail,
                        )
                        return generated
                    except Exception:
                        logger.exception(
                            "Sandbox analyst fallback to direct LLM generation failed",
                            extra={
                                "event": "sql.generation.analyst_fallback_to_llm_failed",
                                "stepId": step.id,
                                "attempt": attempt_number,
                            },
                        )

                clarification_message = f"SQL generation failed ({error_code})."
                generated = GeneratedStep(
                    index=index,
                    step=step,
                    provider="analyst",
                    status="clarification",
                    sql=None,
                    rationale="",
                    interpretation_notes=[],
                    caveats=[f"SQL generation provider error type: {error_code}"],
                    assumptions=[],
                    clarification_question=clarification_message,
                    not_relevant_reason="",
                    clarification_kind="technical_failure",
                    attempted_sql=None,
                    rows=None,
                    generation_error_detail=error_detail,
                )
        else:
            generated = await self._generate_with_llm(
                message=message,
                step=step,
                history=history,
                prior_sql=prior_sql,
                attempt_number=attempt_number,
                retry_feedback=retry_feedback,
                temporal_scope=temporal_scope,
                dependency_context=dependency_context,
            )

        return GeneratedStep(
            index=index,
            step=generated.step,
            provider=generated.provider,
            status=generated.status,
            sql=generated.sql,
            rationale=generated.rationale,
            interpretation_notes=generated.interpretation_notes,
            caveats=generated.caveats,
            assumptions=generated.assumptions,
            clarification_question=generated.clarification_question,
            not_relevant_reason=generated.not_relevant_reason,
            clarification_kind=generated.clarification_kind,
            attempted_sql=generated.attempted_sql,
            rows=generated.rows,
            generation_error_detail=generated.generation_error_detail,
        )
