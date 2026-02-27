from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Literal

from app.config import settings
from app.models import QueryPlanStep
from app.prompts.templates import sql_prompt
from app.services.llm_json import as_string_list
from app.services.llm_trace import llm_trace_stage, record_llm_trace
from app.services.semantic_model import SemanticModel
from app.services.sql_guardrails import guard_sql
from app.services.stages.sql_stage_models import GeneratedStep

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
_TECHNICAL_ERROR_TOKENS = (
    "syntax error",
    "sql error",
    "database error",
    "execution failed",
    "compilation",
    "invalid identifier",
    "no such",
    "does not exist",
    "not found",
    "order by term does not match",
    "warehouse error",
    "permission denied",
)


def _normalize_generation_type(raw_type: Any) -> Literal["sql_ready", "clarification", "technical_failure", "not_relevant"]:
    normalized = str(raw_type or "").strip().lower().replace("-", "_")
    if normalized in {"sql_ready", "answer", "sql"}:
        return "sql_ready"
    if normalized in {"clarification", "clarify"}:
        return "clarification"
    if normalized in {"technical_failure", "execution_error", "runtime_error", "sql_error"}:
        return "technical_failure"
    if normalized in {"not_relevant", "out_of_domain", "irrelevant"}:
        return "not_relevant"
    return "sql_ready"


def _normalize_rows(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def _is_technical_error_text(text: str) -> bool:
    normalized = str(text).strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in _TECHNICAL_ERROR_TOKENS)


def _assumptions_indicate_sql_failure(assumptions: list[str]) -> bool:
    for item in assumptions:
        lowered = item.strip().lower()
        if "sql execution attempt" in lowered and "failed" in lowered:
            return True
        if "sql generation attempt" in lowered and "failed" in lowered:
            return True
    return False


class SqlStepGenerator:
    def __init__(
        self,
        *,
        model: SemanticModel,
        ask_llm_json: AskLlmJsonFn,
        analyst_fn: AnalystFn | None = None,
    ) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._analyst_fn = analyst_fn

    async def _generate_with_analyst(
        self,
        *,
        step: QueryPlanStep,
        history: list[str],
        conversation_id: str,
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None,
    ) -> GeneratedStep:
        if self._analyst_fn is None:
            raise RuntimeError("Analyst provider is not configured.")

        analyst_request = {
            "conversation_id": f"{conversation_id}::sub::{step.id}",
            "message": step.goal,
            "history": history,
            "step_id": step.id,
            "retry_feedback": retry_feedback or [],
        }

        with llm_trace_stage(
            "sql_generation",
            {
                "provider": "analyst",
                "stepId": step.id,
                "stepGoal": step.goal,
                "attempt": attempt_number,
                "retryFeedbackCount": len(retry_feedback or []),
                "retryFeedback": (retry_feedback or [])[-2:],
            },
        ):
            analyst_payload = await self._analyst_fn(
                conversation_id=str(analyst_request["conversation_id"]),
                message=str(analyst_request["message"]),
                history=history,
                step_id=step.id,
                retry_feedback=retry_feedback or [],
            )
            record_llm_trace(
                provider="analyst",
                system_prompt="",
                user_prompt=json.dumps(analyst_request, ensure_ascii=True),
                max_tokens=None,
                temperature=None,
                parsed_response=analyst_payload,
            )

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
        attempted_sql = str(analyst_payload.get("failedSql", "")).strip() or candidate_sql
        rationale = str(analyst_payload.get("lightResponse", "") or analyst_payload.get("explanation", "")).strip()
        assumptions = as_string_list(analyst_payload.get("assumptions"), max_items=4)
        payload_rows = _normalize_rows(analyst_payload.get("rows"))
        technical_error = str(analyst_payload.get("error", "")).strip()

        guarded_sql = guard_sql(candidate_sql, self._model) if candidate_sql else None
        if generation_type == "sql_ready" and not guarded_sql:
            generation_type = "technical_failure"
            technical_error = technical_error or "Generated SQL violated guardrails."

        if generation_type == "clarification":
            if _is_technical_error_text(clarification_question):
                technical_error = technical_error or clarification_question
                clarification_question = ""
                generation_type = "technical_failure"
            elif attempted_sql and _assumptions_indicate_sql_failure(assumptions):
                generation_type = "technical_failure"
                technical_error = technical_error or "Generated SQL failed execution."

        return GeneratedStep(
            index=-1,
            step=step,
            provider="analyst",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            assumptions=assumptions,
            clarification_question=clarification_question,
            technical_error=technical_error,
            not_relevant_reason=not_relevant_reason,
            attempted_sql=attempted_sql or None,
            rows=payload_rows,
        )

    async def _generate_with_llm(
        self,
        *,
        message: str,
        route: str,
        step: QueryPlanStep,
        history: list[str],
        prior_sql: list[str],
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None,
    ) -> GeneratedStep:
        sql_text = ""
        rationale = ""
        clarification_question = ""
        technical_error = ""
        not_relevant_reason = ""
        assumptions: list[str] = []
        generation_type: Literal["sql_ready", "clarification", "technical_failure", "not_relevant"] = "sql_ready"
        attempted_sql: str | None = None

        try:
            system_prompt, user_prompt = sql_prompt(
                message,
                route,
                step.id,
                step.goal,
                self._model,
                prior_sql,
                history,
                retry_feedback=retry_feedback,
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
            assumptions.extend(as_string_list(payload.get("assumptions"), max_items=4))
            technical_error = str(payload.get("error", "")).strip()

            if generation_type == "clarification":
                if _is_technical_error_text(clarification_question):
                    technical_error = technical_error or clarification_question
                    clarification_question = ""
                    generation_type = "technical_failure"
                    candidate_sql = ""
                else:
                    clarification_question = (
                        clarification_question
                        or rationale
                        or f"SQL generation requires clarification for step {step.id}."
                    )
                    candidate_sql = ""
            elif generation_type == "technical_failure":
                technical_error = (
                    technical_error
                    or clarification_question
                    or rationale
                    or f"SQL generation failed for step {step.id}."
                )
                clarification_question = ""
                candidate_sql = ""
            elif generation_type == "not_relevant":
                candidate_sql = ""
            elif candidate_sql:
                sql_text = candidate_sql
        except Exception as error:
            generation_type = "technical_failure"
            clarification_question = ""
            technical_error = str(error).strip() or f"SQL generation failed for step {step.id}."
            assumptions.append(f"SQL generation failed: {error}")

        guarded_sql = guard_sql(sql_text, self._model) if generation_type == "sql_ready" else None
        if generation_type == "sql_ready" and not guarded_sql:
            generation_type = "technical_failure"
            clarification_question = ""
            technical_error = technical_error or rationale or f"Generated SQL violated guardrails for step {step.id}."

        return GeneratedStep(
            index=-1,
            step=step,
            provider="llm",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            assumptions=assumptions,
            clarification_question=clarification_question,
            technical_error=technical_error,
            not_relevant_reason=not_relevant_reason,
            attempted_sql=attempted_sql,
            rows=None,
        )

    async def generate(
        self,
        *,
        index: int,
        message: str,
        route: str,
        step: QueryPlanStep,
        history: list[str],
        prior_sql: list[str],
        conversation_id: str,
        attempt_number: int,
        retry_feedback: list[dict[str, Any]] | None = None,
    ) -> GeneratedStep:
        generated: GeneratedStep
        if self._analyst_fn is not None:
            try:
                generated = await self._generate_with_analyst(
                    step=step,
                    history=history,
                    conversation_id=conversation_id,
                    attempt_number=attempt_number,
                    retry_feedback=retry_feedback,
                )
            except Exception:
                generated = await self._generate_with_llm(
                    message=message,
                    route=route,
                    step=step,
                    history=history,
                    prior_sql=prior_sql,
                    attempt_number=attempt_number,
                    retry_feedback=retry_feedback,
                )
        else:
            generated = await self._generate_with_llm(
                message=message,
                route=route,
                step=step,
                history=history,
                prior_sql=prior_sql,
                attempt_number=attempt_number,
                retry_feedback=retry_feedback,
            )

        return GeneratedStep(
            index=index,
            step=generated.step,
            provider=generated.provider,
            status=generated.status,
            sql=generated.sql,
            rationale=generated.rationale,
            assumptions=generated.assumptions,
            clarification_question=generated.clarification_question,
            technical_error=generated.technical_error,
            not_relevant_reason=generated.not_relevant_reason,
            attempted_sql=generated.attempted_sql,
            rows=generated.rows,
        )
