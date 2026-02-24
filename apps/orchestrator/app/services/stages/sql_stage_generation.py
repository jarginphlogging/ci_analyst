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


def _normalize_generation_type(raw_type: Any) -> Literal["sql_ready", "clarification", "not_relevant"]:
    normalized = str(raw_type or "").strip().lower().replace("-", "_")
    if normalized in {"sql_ready", "answer", "sql"}:
        return "sql_ready"
    if normalized in {"clarification", "clarify"}:
        return "clarification"
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
    ) -> GeneratedStep:
        if self._analyst_fn is None:
            raise RuntimeError("Analyst provider is not configured.")

        analyst_request = {
            "conversation_id": f"{conversation_id}::sub::{step.id}",
            "message": step.goal,
            "history": history,
            "step_id": step.id,
        }

        with llm_trace_stage(
            "sql_generation",
            {
                "provider": "analyst",
                "stepId": step.id,
                "stepGoal": step.goal,
                "attempt": attempt_number,
            },
        ):
            analyst_payload = await self._analyst_fn(
                conversation_id=str(analyst_request["conversation_id"]),
                message=str(analyst_request["message"]),
                history=history,
                step_id=step.id,
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
        rationale = str(analyst_payload.get("lightResponse", "") or analyst_payload.get("explanation", "")).strip()
        assumptions = as_string_list(analyst_payload.get("assumptions"), max_items=4)
        payload_rows = _normalize_rows(analyst_payload.get("rows"))

        guarded_sql = guard_sql(candidate_sql, self._model) if candidate_sql else None
        if generation_type == "sql_ready" and not guarded_sql:
            generation_type = "clarification"
            clarification_question = (
                clarification_question
                or "Could you clarify the metric, segment, and time window so I can generate the right SQL?"
            )

        return GeneratedStep(
            index=-1,
            step=step,
            provider="analyst",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            assumptions=assumptions,
            clarification_question=clarification_question,
            not_relevant_reason=not_relevant_reason,
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
    ) -> GeneratedStep:
        sql_text = ""
        rationale = ""
        clarification_question = ""
        not_relevant_reason = ""
        assumptions: list[str] = []
        generation_type: Literal["sql_ready", "clarification", "not_relevant"] = "sql_ready"

        try:
            system_prompt, user_prompt = sql_prompt(
                message,
                route,
                step.id,
                step.goal,
                self._model,
                prior_sql,
                history,
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
            assumptions.extend(as_string_list(payload.get("assumptions"), max_items=4))

            if generation_type == "clarification":
                clarification_question = (
                    clarification_question
                    or "Could you clarify the requested metric, grain, and time window before I generate SQL?"
                )
                candidate_sql = ""
            elif generation_type == "not_relevant":
                candidate_sql = ""
            elif candidate_sql:
                sql_text = candidate_sql
        except Exception as error:
            generation_type = "clarification"
            clarification_question = (
                "I couldn't generate SQL for that step. Please clarify the metric, grain, and time window."
            )
            assumptions.append(f"SQL generation failed: {error}")

        guarded_sql = guard_sql(sql_text, self._model) if generation_type == "sql_ready" else None
        if generation_type == "sql_ready" and not guarded_sql:
            generation_type = "clarification"
            clarification_question = (
                clarification_question
                or "Could you clarify the requested metric, grain, and time window before I generate SQL?"
            )

        return GeneratedStep(
            index=-1,
            step=step,
            provider="llm",
            status=generation_type,
            sql=guarded_sql,
            rationale=rationale,
            assumptions=assumptions,
            clarification_question=clarification_question,
            not_relevant_reason=not_relevant_reason,
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
    ) -> GeneratedStep:
        generated: GeneratedStep
        if self._analyst_fn is not None:
            try:
                generated = await self._generate_with_analyst(
                    step=step,
                    history=history,
                    conversation_id=conversation_id,
                    attempt_number=attempt_number,
                )
            except Exception:
                generated = await self._generate_with_llm(
                    message=message,
                    route=route,
                    step=step,
                    history=history,
                    prior_sql=prior_sql,
                    attempt_number=attempt_number,
                )
        else:
            generated = await self._generate_with_llm(
                message=message,
                route=route,
                step=step,
                history=history,
                prior_sql=prior_sql,
                attempt_number=attempt_number,
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
            not_relevant_reason=generated.not_relevant_reason,
            rows=generated.rows,
        )
