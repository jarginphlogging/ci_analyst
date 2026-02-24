from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.models import QueryPlanStep
from app.prompts.templates import plan_prompt
from app.services.llm_trace import llm_trace_stage
from app.services.semantic_model import SemanticModel, semantic_model_planner_context
from app.services.semantic_model_yaml import (
    SemanticModelYaml,
    load_semantic_model_yaml,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]

PLANNER_MAX_STEPS = 5
OUT_OF_DOMAIN_MESSAGE = "I can only answer questions about Customer Insights."
TOO_COMPLEX_MESSAGE = "Your request is too complex, please simplify it and try again."


@dataclass(frozen=True)
class PlannerDecision:
    relevance: Literal["in_domain", "out_of_domain", "unclear"]
    relevance_reason: str
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


def _strip_table_references(text: str) -> str:
    replaced = re.sub(r"\bcia_[a-z0-9_]+\b", "governed customer insights data", text, flags=re.IGNORECASE)
    replaced = re.sub(r"\bfrom\s+the\s+([^.,;]+?)\s+table\b", "from governed customer insights data", replaced, flags=re.IGNORECASE)
    return " ".join(replaced.split())


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


def _enforce_planner_guardrails(
    *,
    message: str,
    steps: list[QueryPlanStep],
) -> list[QueryPlanStep]:
    if not steps:
        return [QueryPlanStep(id="step_1", goal=_direct_task_goal(message), dependsOn=[], independent=True)]

    sanitized: list[QueryPlanStep] = []
    for step in steps:
        goal = _strip_unrequested_schema_terms(message, _strip_table_references(step.goal))
        sanitized.append(step.model_copy(update={"goal": goal}))
    return sanitized


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


def _message_tokens(message: str) -> set[str]:
    return {
        token.strip().lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", message)
        if token.strip()
    }


def _has_domain_signal(message: str, guide: SemanticModelYaml) -> bool:
    normalized_message = _normalized(message)
    if not normalized_message:
        return False

    phrases = {phrase for phrase in guide.domain_phrases if len(phrase) >= 4}
    if any(phrase in normalized_message for phrase in phrases):
        return True

    message_tokens = _message_tokens(message)
    guide_terms = set(guide.domain_terms)
    matches = message_tokens.intersection(guide_terms)
    return len(matches) >= 2


class PlannerStage:
    def __init__(self, *, model: SemanticModel, ask_llm_json: AskLlmJsonFn) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._semantic_yaml = load_semantic_model_yaml()
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

            if relevance == "out_of_domain":
                return PlannerDecision(
                    relevance="out_of_domain",
                    relevance_reason=relevance_reason or "Question is outside semantic_model.yaml scope.",
                    steps=[],
                    stop_reason="out_of_domain",
                    stop_message=OUT_OF_DOMAIN_MESSAGE,
                )

            if too_complex or (isinstance(raw_tasks, list) and len(raw_tasks) > max_steps):
                return PlannerDecision(
                    relevance=relevance,
                    relevance_reason=relevance_reason or "Minimum independent decomposition exceeds step limit.",
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
                steps=steps,
                stop_reason="none",
            )
        except Exception:
            relevance: Literal["in_domain", "out_of_domain", "unclear"] = (
                "in_domain" if _has_domain_signal(message, self._semantic_yaml) else "unclear"
            )
            steps = _heuristic_plan(message, max_steps=max_steps)
            steps = _enforce_planner_guardrails(message=message, steps=steps)
            return PlannerDecision(
                relevance=relevance,
                relevance_reason="LLM planner unavailable; used deterministic decomposition fallback.",
                steps=steps,
                stop_reason="none",
            )
