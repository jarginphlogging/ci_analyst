from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.config import settings
from app.models import PresentationIntent, QueryPlanStep
from app.prompts.templates import plan_prompt
from app.services.llm_trace import llm_trace_stage
from app.services.semantic_model import SemanticModel, semantic_model_planner_context

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]

PLANNER_MAX_STEPS = 5
OUT_OF_DOMAIN_MESSAGE = "I can only answer questions about Customer Insights."
TOO_COMPLEX_MESSAGE = "Your request is too complex, please simplify it and try again."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannerDecision:
    relevance: Literal["in_domain", "out_of_domain", "unclear"]
    relevance_reason: str
    presentation_intent: PresentationIntent
    steps: list[QueryPlanStep]
    stop_reason: Literal["none", "out_of_domain", "too_complex"]
    stop_message: str | None = None


class PlannerBlockedError(RuntimeError):
    def __init__(
        self,
        *,
        stop_reason: Literal["out_of_domain", "too_complex"],
        user_message: str,
    ) -> None:
        super().__init__(user_message)
        self.stop_reason = stop_reason
        self.user_message = user_message


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _direct_task_goal(message: str) -> str:
    return " ".join(message.strip().split())


def _normalize_display_type(value: Any) -> Literal["inline", "table", "chart"]:
    raw = str(value or "").strip().lower()
    if raw in {"inline", "table", "chart"}:
        return raw
    return "table"


def _normalize_chart_type(value: Any) -> Literal["line", "bar", "stacked_bar", "grouped_bar"] | None:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"line", "bar", "stacked_bar", "grouped_bar"}:
        return raw
    return None


def _normalize_table_style(value: Any) -> Literal["simple", "ranked", "comparison"] | None:
    raw = str(value or "").strip().lower()
    if raw in {"simple", "ranked", "comparison"}:
        return raw
    return None


def _fallback_presentation_intent(message: str) -> PresentationIntent:
    query = message.lower()
    if any(token in query for token in ("trend", "over time", "month", "weekly", "daily", "quarter", "year")):
        return PresentationIntent(
            displayType="chart",
            chartType="line",
            rationale="Time-oriented request defaults to line chart.",
        )
    if any(token in query for token in ("top", "bottom", "rank")):
        return PresentationIntent(
            displayType="table",
            tableStyle="ranked",
            rationale="Ranking request defaults to ranked table.",
        )
    return PresentationIntent(
        displayType="table",
        tableStyle="simple",
        rationale="Default to simple table when presentation intent is uncertain.",
    )


def _coerce_presentation_intent(raw: Any, message: str) -> PresentationIntent:
    if not isinstance(raw, dict):
        return _fallback_presentation_intent(message)
    display_type = _normalize_display_type(raw.get("displayType"))
    chart_type = _normalize_chart_type(raw.get("chartType"))
    table_style = _normalize_table_style(raw.get("tableStyle"))
    rationale = str(raw.get("rationale", "")).strip()
    if display_type == "chart" and chart_type is None:
        chart_type = "line"
    if display_type == "table" and table_style is None:
        table_style = "simple"
    if display_type == "inline":
        chart_type = None
        table_style = None
    return PresentationIntent(
        displayType=display_type,
        chartType=chart_type,
        tableStyle=table_style,
        rationale=rationale,
    )


def _enforce_planner_guardrails(
    *,
    message: str,
    steps: list[QueryPlanStep],
) -> list[QueryPlanStep]:
    if not steps:
        return [QueryPlanStep(id="step_1", goal=_direct_task_goal(message), dependsOn=[], independent=True)]

    sanitized: list[QueryPlanStep] = []
    for step in steps:
        goal = _strip_unrequested_schema_terms(message, step.goal)
        sanitized.append(step.model_copy(update={"goal": goal}))
    return sanitized


def _message_schema_tokens(message: str) -> set[str]:
    return {token.lower() for token in re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", message)}


def _strip_unrequested_schema_terms(message: str, text: str) -> str:
    allowed_tokens = _message_schema_tokens(message)

    def _replacement(match: re.Match[str]) -> str:
        token = match.group(0)
        lowered = token.lower()
        if lowered in allowed_tokens:
            return token
        if lowered.startswith("cia_"):
            return "governed customer insights data"
        if lowered.endswith("_id"):
            return "business identifier"
        if re.search(r"_(date|time|day|week|month|quarter|year)$", lowered):
            return "requested time window"
        return "requested metric"

    replaced = re.sub(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", _replacement, text, flags=re.IGNORECASE)
    return " ".join(replaced.split())


def _heuristic_plan(message: str, max_steps: int) -> list[QueryPlanStep]:
    _ = max_steps
    return [QueryPlanStep(id="step_1", goal=_direct_task_goal(message), dependsOn=[], independent=True)]


def _extract_steps(raw_tasks: Any, max_steps: int) -> list[QueryPlanStep]:
    if not isinstance(raw_tasks, list):
        return []

    steps: list[QueryPlanStep] = []
    seen: set[str] = set()
    for entry in raw_tasks:
        task_text = ""
        depends_on: list[str] = []
        independent = True
        if isinstance(entry, dict):
            task_text = str(entry.get("task", "") or entry.get("goal", "")).strip()
            raw_depends = entry.get("dependsOn", entry.get("depends_on", []))
            if isinstance(raw_depends, list):
                depends_on = [str(item).strip() for item in raw_depends if str(item).strip()]
            independent = not depends_on if "independent" not in entry else bool(entry.get("independent"))
        elif isinstance(entry, str):
            task_text = entry.strip()
        if not task_text:
            continue

        key = _normalized(task_text)
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            QueryPlanStep(
                id=f"step_{len(steps) + 1}",
                goal=task_text,
                dependsOn=depends_on,
                independent=independent,
            )
        )
        if len(steps) >= max_steps:
            break
    return steps


class PlannerStage:
    def __init__(self, *, model: SemanticModel, ask_llm_json: AskLlmJsonFn) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._planner_scope_context = semantic_model_planner_context(self._model)

    async def create_plan(self, message: str, history: list[str]) -> PlannerDecision:
        max_steps = PLANNER_MAX_STEPS
        system_prompt, user_prompt = plan_prompt(
            message,
            self._planner_scope_context,
            max_steps,
            history,
        )

        try:
            with llm_trace_stage(
                "plan_generation",
                {
                    "historyDepth": len(history),
                    "maxSteps": max_steps,
                },
            ):
                payload = await self._ask_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=900,
                )
            relevance_raw = str(payload.get("relevance", "unclear")).strip().lower()
            relevance: Literal["in_domain", "out_of_domain", "unclear"] = "unclear"
            if relevance_raw in {"in_domain", "out_of_domain", "unclear"}:
                relevance = relevance_raw

            relevance_reason = str(payload.get("relevanceReason", "")).strip()
            too_complex = _as_bool(payload.get("tooComplex"))
            raw_tasks = payload.get("tasks", payload.get("steps", []))
            steps = _extract_steps(raw_tasks, max_steps=max_steps)
            presentation_intent = _coerce_presentation_intent(payload.get("presentationIntent"), message)

            if relevance == "out_of_domain":
                return PlannerDecision(
                    relevance="out_of_domain",
                    relevance_reason=relevance_reason or "Question is outside semantic_model.yaml scope.",
                    presentation_intent=presentation_intent,
                    steps=[],
                    stop_reason="out_of_domain",
                    stop_message=OUT_OF_DOMAIN_MESSAGE,
                )

            if too_complex or (isinstance(raw_tasks, list) and len(raw_tasks) > max_steps):
                return PlannerDecision(
                    relevance=relevance,
                    relevance_reason=relevance_reason or "Minimum independent decomposition exceeds step limit.",
                    presentation_intent=presentation_intent,
                    steps=[],
                    stop_reason="too_complex",
                    stop_message=TOO_COMPLEX_MESSAGE,
                )

            if not steps:
                steps = _heuristic_plan(message, max_steps=max_steps)
            steps = _enforce_planner_guardrails(message=message, steps=steps)

            return PlannerDecision(
                relevance=relevance,
                relevance_reason=relevance_reason or "Planner produced independent decomposition.",
                presentation_intent=presentation_intent,
                steps=steps,
                stop_reason="none",
            )
        except Exception:
            if settings.provider_mode in {"sandbox", "prod"}:
                raise
            logger.exception(
                "Planner LLM call failed; using deterministic fallback",
                extra={
                    "event": "planner.fallback_on_error",
                    "historyDepth": len(history),
                },
            )
            steps = _heuristic_plan(message, max_steps=max_steps)
            steps = _enforce_planner_guardrails(message=message, steps=steps)
            return PlannerDecision(
                relevance="unclear",
                relevance_reason="LLM planner unavailable; used deterministic decomposition fallback.",
                presentation_intent=_fallback_presentation_intent(message),
                steps=steps,
                stop_reason="none",
            )
