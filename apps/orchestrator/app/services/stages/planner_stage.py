from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.models import AnalysisType, QueryPlanStep
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
DEFAULT_ANALYSIS_TYPE: AnalysisType = "aggregation_summary_stats"
ANALYSIS_TYPES: tuple[AnalysisType, ...] = (
    "trend_over_time",
    "ranking_top_n_bottom_n",
    "comparison",
    "composition_breakdown",
    "aggregation_summary_stats",
    "point_in_time_snapshot",
    "period_over_period_change",
    "anomaly_outlier_detection",
    "drill_down_root_cause",
    "correlation_relationship",
    "cohort_analysis",
    "distribution_histogram",
    "forecasting_projection",
    "threshold_filter_segmentation",
    "cumulative_running_total",
    "rate_ratio_efficiency",
)
ANALYSIS_VISUAL_SHAPE_HINTS: dict[AnalysisType, str] = {
    "trend_over_time": "a time-ordered series for the requested metric and period",
    "ranking_top_n_bottom_n": "a ranked entity list with the requested metric values",
    "comparison": "side-by-side values for the compared groups or periods",
    "composition_breakdown": "a parts-of-whole breakdown for the requested metric",
    "aggregation_summary_stats": "a compact summary of the requested aggregate metric(s)",
    "point_in_time_snapshot": "an as-of snapshot of the requested current-state metric(s)",
    "period_over_period_change": "prior and current values with explicit change/delta",
    "anomaly_outlier_detection": "a series or distribution that identifies unusual points",
    "drill_down_root_cause": "a driver breakdown from aggregate to contributing segments",
    "correlation_relationship": "paired measures suitable for relationship analysis",
    "cohort_analysis": "cohort-by-period outputs for cohort comparison",
    "distribution_histogram": "bucketed or percentile distribution outputs",
    "forecasting_projection": "historical values plus projected future periods",
    "threshold_filter_segmentation": "a filtered table of records matching criteria",
    "cumulative_running_total": "a time-ordered running total series",
    "rate_ratio_efficiency": "ratio/rate outputs by the requested group or period",
}
ANALYSIS_VISUAL_SHAPE_KEYWORDS: dict[AnalysisType, tuple[str, ...]] = {
    "trend_over_time": ("trend", "time", "monthly", "weekly", "daily", "series"),
    "ranking_top_n_bottom_n": ("top", "bottom", "rank", "descending", "ascending"),
    "comparison": ("compare", "versus", "vs", "side-by-side", "difference", "delta"),
    "composition_breakdown": ("breakdown", "mix", "share", "composition", "parts"),
    "aggregation_summary_stats": ("total", "sum", "average", "median", "count", "min", "max", "aggregate"),
    "point_in_time_snapshot": ("current", "as of", "snapshot", "today", "right now"),
    "period_over_period_change": ("mom", "qoq", "yoy", "change", "delta", "variance", "prior"),
    "anomaly_outlier_detection": ("anomaly", "outlier", "spike", "drop", "unusual"),
    "drill_down_root_cause": ("driver", "root cause", "drill", "decompose", "why"),
    "correlation_relationship": ("correlation", "relationship", "paired", "x and y"),
    "cohort_analysis": ("cohort", "vintage", "retention"),
    "distribution_histogram": ("distribution", "histogram", "bucket", "percentile", "spread"),
    "forecasting_projection": ("forecast", "projection", "projected", "future"),
    "threshold_filter_segmentation": ("filter", "segment", "criteria", "list", "records"),
    "cumulative_running_total": ("cumulative", "running total", "ytd"),
    "rate_ratio_efficiency": ("rate", "ratio", "conversion", "utilization", "efficiency"),
}


@dataclass(frozen=True)
class PlannerDecision:
    relevance: Literal["in_domain", "out_of_domain", "unclear"]
    relevance_reason: str
    analysis_type: AnalysisType
    secondary_analysis_type: AnalysisType | None
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


def _normalize_analysis_type(value: Any) -> AnalysisType:
    raw = str(value or "").strip().lower()
    for candidate in ANALYSIS_TYPES:
        if raw == candidate:
            return candidate
    return DEFAULT_ANALYSIS_TYPE


def _fallback_analysis_type(message: str) -> AnalysisType:
    text = _normalized(message)
    if any(keyword in text for keyword in ("top", "bottom", "rank")):
        return "ranking_top_n_bottom_n"
    if any(keyword in text for keyword in ("trend", "over time")):
        return "trend_over_time"
    if any(keyword in text for keyword in ("compare", "versus", "vs")):
        return "comparison"
    if any(keyword in text for keyword in ("breakdown", "mix", "composition")):
        return "composition_breakdown"
    if any(keyword in text for keyword in ("yoy", "qoq", "mom", "delta", "change rate", "variance")):
        return "period_over_period_change"
    if any(keyword in text for keyword in ("distribution", "histogram", "spread")):
        return "distribution_histogram"
    if any(keyword in text for keyword in ("snapshot", "current", "right now", "today")):
        return "point_in_time_snapshot"
    if any(keyword in text for keyword in ("correlat", "relationship")):
        return "correlation_relationship"
    if any(keyword in text for keyword in ("cohort", "retention", "vintage")):
        return "cohort_analysis"
    if any(keyword in text for keyword in ("forecast", "project")):
        return "forecasting_projection"
    if any(keyword in text for keyword in ("running total", "cumulative", "ytd")):
        return "cumulative_running_total"
    if any(keyword in text for keyword in ("rate", "ratio", "efficiency", "conversion", "utilization")):
        return "rate_ratio_efficiency"
    if any(keyword in text for keyword in ("outlier", "anomaly", "spike", "unusual")):
        return "anomaly_outlier_detection"
    if any(keyword in text for keyword in ("why", "root cause", "driver", "drill")):
        return "drill_down_root_cause"
    if any(keyword in text for keyword in ("threshold", "filter", "segment", "criteria", "which")):
        return "threshold_filter_segmentation"
    return DEFAULT_ANALYSIS_TYPE


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


def _task_matches_visual_shape(goal: str, analysis_type: AnalysisType) -> bool:
    text = _normalized(goal)
    return any(keyword in text for keyword in ANALYSIS_VISUAL_SHAPE_KEYWORDS.get(analysis_type, ()))


def _ensure_visual_shape_task(
    *,
    analysis_type: AnalysisType,
    steps: list[QueryPlanStep],
) -> list[QueryPlanStep]:
    if not steps:
        return steps
    if any(_task_matches_visual_shape(step.goal, analysis_type) for step in steps):
        return steps

    shape_hint = ANALYSIS_VISUAL_SHAPE_HINTS.get(analysis_type)
    if not shape_hint:
        return steps

    first = steps[0]
    patched_goal = f"{first.goal.rstrip('.')} Return output shaped as {shape_hint}."
    return [first.model_copy(update={"goal": patched_goal}), *steps[1:]]


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
            analysis_type = _normalize_analysis_type(payload.get("analysisType"))
            secondary_raw = str(payload.get("secondaryAnalysisType", "")).strip()
            secondary_analysis_type = _normalize_analysis_type(secondary_raw) if secondary_raw else None
            if secondary_analysis_type == analysis_type:
                secondary_analysis_type = None
            too_complex = _as_bool(payload.get("tooComplex"))
            raw_tasks = payload.get("tasks", payload.get("steps", []))
            steps = _extract_steps(raw_tasks, max_steps=max_steps)

            if relevance == "out_of_domain":
                return PlannerDecision(
                    relevance="out_of_domain",
                    relevance_reason=relevance_reason or "Question is outside semantic_model.yaml scope.",
                    analysis_type=analysis_type,
                    secondary_analysis_type=secondary_analysis_type,
                    steps=[],
                    stop_reason="out_of_domain",
                    stop_message=OUT_OF_DOMAIN_MESSAGE,
                )

            if too_complex or (isinstance(raw_tasks, list) and len(raw_tasks) > max_steps):
                return PlannerDecision(
                    relevance=relevance,
                    relevance_reason=relevance_reason or "Minimum independent decomposition exceeds step limit.",
                    analysis_type=analysis_type,
                    secondary_analysis_type=secondary_analysis_type,
                    steps=[],
                    stop_reason="too_complex",
                    stop_message=TOO_COMPLEX_MESSAGE,
                )

            if not steps:
                steps = _heuristic_plan(message, max_steps=max_steps)
            steps = _enforce_planner_guardrails(message=message, steps=steps)
            steps = _ensure_visual_shape_task(analysis_type=analysis_type, steps=steps)

            return PlannerDecision(
                relevance=relevance,
                relevance_reason=relevance_reason or "Planner produced independent decomposition.",
                analysis_type=analysis_type,
                secondary_analysis_type=secondary_analysis_type,
                steps=steps,
                stop_reason="none",
            )
        except Exception:
            relevance: Literal["in_domain", "out_of_domain", "unclear"] = (
                "in_domain" if _has_domain_signal(message, self._semantic_yaml) else "unclear"
            )
            steps = _heuristic_plan(message, max_steps=max_steps)
            steps = _enforce_planner_guardrails(message=message, steps=steps)
            fallback_analysis_type = _fallback_analysis_type(message)
            steps = _ensure_visual_shape_task(analysis_type=fallback_analysis_type, steps=steps)
            return PlannerDecision(
                relevance=relevance,
                relevance_reason="LLM planner unavailable; used deterministic decomposition fallback.",
                analysis_type=fallback_analysis_type,
                secondary_analysis_type=None,
                steps=steps,
                stop_reason="none",
            )
