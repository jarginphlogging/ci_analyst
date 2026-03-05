from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.config import settings
from app.models import PresentationIntent, QueryPlanStep, TemporalScope
from app.prompts.templates import plan_prompt
from app.services.llm_trace import llm_trace_stage
from app.services.semantic_model import SemanticModel, semantic_model_summary

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]

PLANNER_MAX_STEPS = max(1, settings.plan_max_steps)
OUT_OF_DOMAIN_MESSAGE = "I can only answer questions about Customer Insights."
TOO_COMPLEX_MESSAGE = "Your request is too complex, please simplify it and try again."
logger = logging.getLogger(__name__)
_STEP_REF_PATTERN = re.compile(r"(?:^|\b)(?:step|task)?\s*[_\-#:]?\s*(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PlannerDecision:
    relevance: Literal["in_domain", "out_of_domain", "unclear"]
    relevance_reason: str
    presentation_intent: PresentationIntent
    temporal_scope: TemporalScope | None
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


def _normalize_display_type(value: Any) -> Literal["inline", "table", "chart"]:
    raw = str(value or "").strip().lower()
    if raw in {"inline", "table", "chart"}:
        return raw
    return "table"


def _normalize_chart_type(value: Any) -> Literal["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"] | None:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"line", "bar", "stacked_bar", "stacked_area", "grouped_bar"}:
        return raw
    return None


def _normalize_table_style(value: Any) -> Literal["simple", "ranked", "comparison"] | None:
    raw = str(value or "").strip().lower()
    if raw in {"simple", "ranked", "comparison"}:
        return raw
    return None


def _normalize_time_unit(raw: str) -> Literal["day", "week", "month", "quarter", "year"] | None:
    token = raw.strip().lower()
    aliases = {
        "day": "day",
        "days": "day",
        "week": "week",
        "weeks": "week",
        "month": "month",
        "months": "month",
        "quarter": "quarter",
        "quarters": "quarter",
        "year": "year",
        "years": "year",
    }
    return aliases.get(token)


def _infer_granularity(message: str) -> Literal["day", "week", "month", "quarter", "year"] | None:
    text = message.lower()
    patterns: list[tuple[re.Pattern[str], Literal["day", "week", "month", "quarter", "year"]]] = [
        (re.compile(r"\b(by|per)\s+day\b"), "day"),
        (re.compile(r"\bdaily\b"), "day"),
        (re.compile(r"\b(by|per)\s+week\b"), "week"),
        (re.compile(r"\bweekly\b"), "week"),
        (re.compile(r"\b(by|per)\s+month\b"), "month"),
        (re.compile(r"\bmonthly\b"), "month"),
        (re.compile(r"\b(by|per)\s+quarter\b"), "quarter"),
        (re.compile(r"\bquarterly\b"), "quarter"),
        (re.compile(r"\b(by|per)\s+year\b"), "year"),
        (re.compile(r"\byearly\b"), "year"),
    ]
    for pattern, unit in patterns:
        if pattern.search(text):
            return unit
    return None


def _infer_temporal_scope_from_message(message: str) -> TemporalScope | None:
    text = " ".join(message.lower().split())
    last_month = re.search(r"\blast\s+month\b", text)
    if last_month:
        return TemporalScope(unit="month", count=1, granularity=_infer_granularity(message))

    pattern = re.search(r"\blast\s+(\d{1,3})\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b", text)
    if not pattern:
        return None
    count = int(pattern.group(1))
    unit = _normalize_time_unit(pattern.group(2))
    if unit is None:
        return None
    return TemporalScope(unit=unit, count=max(1, count), granularity=_infer_granularity(message) or unit)


def _coerce_temporal_scope(raw: Any, message: str) -> TemporalScope | None:
    inferred = _infer_temporal_scope_from_message(message)
    if not isinstance(raw, dict):
        return inferred

    try:
        scope = TemporalScope.model_validate(raw)
    except Exception:
        return inferred

    if scope.granularity is None and inferred is not None and inferred.granularity is not None:
        return scope.model_copy(update={"granularity": inferred.granularity})
    return scope


def _coerce_presentation_intent(raw: Any, message: str) -> PresentationIntent:
    _ = message
    if not isinstance(raw, dict):
        return PresentationIntent(
            displayType="table",
            tableStyle="simple",
            rationale="Default to simple table when presentation intent is uncertain.",
        )
    display_type = _normalize_display_type(raw.get("displayType"))
    chart_type = _normalize_chart_type(raw.get("chartType"))
    table_style = _normalize_table_style(raw.get("tableStyle"))
    rationale = str(raw.get("rationale", "")).strip()
    ranking_objectives_raw = raw.get("rankingObjectives", [])
    ranking_objectives: list[str] = []
    if isinstance(ranking_objectives_raw, list):
        seen: set[str] = set()
        for item in ranking_objectives_raw[:4]:
            objective = str(item).strip()
            if not objective:
                continue
            key = objective.lower()
            if key in seen:
                continue
            seen.add(key)
            ranking_objectives.append(objective)
    if display_type == "chart" and chart_type is None:
        chart_type = "line"
    if display_type == "table" and table_style is None:
        table_style = "simple"
    if display_type != "table" or table_style != "ranked":
        ranking_objectives = []
    if display_type == "inline":
        chart_type = None
        table_style = None
        ranking_objectives = []
    return PresentationIntent(
        displayType=display_type,
        chartType=chart_type,
        tableStyle=table_style,
        rationale=rationale,
        rankingObjectives=ranking_objectives,
    )


def _extract_steps(raw_tasks: Any, max_steps: int) -> list[QueryPlanStep]:
    if not isinstance(raw_tasks, list):
        return []

    extracted: list[tuple[str, list[str], bool | None]] = []
    seen: set[str] = set()
    for entry in raw_tasks:
        task_text = ""
        depends_on_raw: list[str] = []
        independent_override: bool | None = None
        if isinstance(entry, dict):
            task_text = str(entry.get("task", "") or entry.get("goal", "")).strip()
            raw_depends = entry.get("dependsOn", entry.get("depends_on", []))
            if isinstance(raw_depends, list):
                depends_on_raw = [str(item).strip() for item in raw_depends if str(item).strip()]
            if "independent" in entry:
                independent_override = bool(entry.get("independent"))
        elif isinstance(entry, str):
            task_text = entry.strip()
        if not task_text:
            continue

        key = _normalized(task_text)
        if key in seen:
            continue
        seen.add(key)
        extracted.append((task_text, depends_on_raw, independent_override))
        if len(extracted) >= max_steps:
            break

    if not extracted:
        return []

    ids = [f"step_{index + 1}" for index in range(len(extracted))]
    id_to_index = {step_id: index for index, step_id in enumerate(ids)}
    goal_to_id = {_normalized(task_text): ids[index] for index, (task_text, _, _) in enumerate(extracted)}

    def _resolve_dependency(raw_dependency: str, current_index: int) -> str | None:
        token = raw_dependency.strip()
        if not token:
            return None

        direct_index = id_to_index.get(token)
        if direct_index is not None and direct_index < current_index:
            return token

        normalized_token = _normalized(token)
        goal_match_id = goal_to_id.get(normalized_token)
        if goal_match_id is not None and id_to_index.get(goal_match_id, -1) < current_index:
            return goal_match_id

        ordinal_match = _STEP_REF_PATTERN.search(token)
        if ordinal_match:
            candidate_index = int(ordinal_match.group(1)) - 1
            if 0 <= candidate_index < current_index:
                return ids[candidate_index]
        return None

    steps: list[QueryPlanStep] = []
    for index, (task_text, depends_on_raw, independent_override) in enumerate(extracted):
        depends_on: list[str] = []
        seen_dependencies: set[str] = set()
        for raw_dependency in depends_on_raw:
            resolved = _resolve_dependency(raw_dependency, index)
            if not resolved or resolved in seen_dependencies:
                continue
            seen_dependencies.add(resolved)
            depends_on.append(resolved)
        independent = independent_override if independent_override is not None else not depends_on
        if depends_on:
            independent = False
        steps.append(
            QueryPlanStep(
                id=ids[index],
                goal=task_text,
                dependsOn=depends_on,
                independent=independent,
            )
        )
    return steps


class PlannerStage:
    def __init__(self, *, model: SemanticModel, ask_llm_json: AskLlmJsonFn) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._semantic_model_summary = semantic_model_summary(self._model)

    async def create_plan(self, message: str, history: list[str]) -> PlannerDecision:
        max_steps = PLANNER_MAX_STEPS
        system_prompt, user_prompt = plan_prompt(
            message,
            self._semantic_model_summary,
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
                    temporal_scope=None,
                    steps=[],
                    stop_reason="out_of_domain",
                    stop_message=OUT_OF_DOMAIN_MESSAGE,
                )

            if too_complex or (isinstance(raw_tasks, list) and len(raw_tasks) > max_steps):
                return PlannerDecision(
                    relevance=relevance,
                    relevance_reason=relevance_reason or "Minimum independent decomposition exceeds step limit.",
                    presentation_intent=presentation_intent,
                    temporal_scope=None,
                    steps=[],
                    stop_reason="too_complex",
                    stop_message=TOO_COMPLEX_MESSAGE,
                )

            if not steps:
                raise RuntimeError("Planner returned no executable tasks.")

            return PlannerDecision(
                relevance=relevance,
                relevance_reason=relevance_reason or "Planner produced independent decomposition.",
                presentation_intent=presentation_intent,
                temporal_scope=_coerce_temporal_scope(payload.get("temporalScope"), message),
                steps=steps,
                stop_reason="none",
            )
        except Exception:
            logger.exception(
                "Planner LLM call failed",
                extra={
                    "event": "planner.failed",
                    "historyDepth": len(history),
                },
            )
            raise
