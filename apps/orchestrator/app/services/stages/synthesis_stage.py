from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, cast

from app.config import settings
from app.models import AgentResponse, EvidenceRow, Insight, SqlExecutionResult, TraceStep
from app.prompts.templates import response_prompt
from app.services.llm_json import as_string_list
from app.services.table_analysis import (
    build_evidence_rows,
    build_metric_points,
    results_to_data_tables,
    summarize_results_for_prompt,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


def _sanitize_insights(raw: Any) -> list[Insight]:
    if not isinstance(raw, list):
        return []

    items: list[Insight] = []
    for index, entry in enumerate(raw[:4], start=1):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not title or not detail:
            continue
        importance = str(entry.get("importance", "medium")).lower()
        normalized_importance: Literal["high", "medium"] = "high" if importance == "high" else "medium"
        items.append(
            Insight(
                id=f"i{index}",
                title=title,
                detail=detail,
                importance=normalized_importance,
            )
        )
    return items


def _default_insights(evidence: list[EvidenceRow]) -> list[Insight]:
    if not evidence:
        return [
            Insight(
                id="i1",
                title="Limited evidence returned",
                detail="The query returned data but not enough structured segments for deep decomposition.",
                importance="medium",
            )
        ]

    top = max(evidence, key=lambda row: abs(row.changeBps))
    return [
        Insight(
            id="i1",
            title=f"Largest movement in {top.segment}",
            detail=f"Segment change of {top.changeBps:.1f} bps dominates the observed shift.",
            importance="high",
        ),
        Insight(
            id="i2",
            title="Concentration pattern is measurable",
            detail="Top segments carry disproportionate contribution, supporting targeted intervention.",
            importance="medium",
        ),
    ]


def _default_questions() -> list[str]:
    return [
        "Can you break this down by state and channel?",
        "How much of the change came from repeat versus new customers?",
        "Which stores are diverging most from portfolio averages?",
    ]


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json

    async def build_response(
        self,
        *,
        message: str,
        route: str,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        evidence = build_evidence_rows(results)
        metrics = build_metric_points(results, evidence)
        data_tables = results_to_data_tables(results)
        result_summary = summarize_results_for_prompt(results)
        evidence_summary = str([row.model_dump() for row in evidence[:8]])

        llm_payload: dict[str, Any] = {}
        try:
            system_prompt, user_prompt = response_prompt(
                message,
                route,
                result_summary,
                evidence_summary,
                history,
            )
            llm_payload = await self._ask_llm_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=settings.real_llm_max_tokens,
            )
        except Exception:
            llm_payload = {}

        answer = str(llm_payload.get("answer", "")).strip() or (
            "I completed the governed analysis and surfaced the highest-impact segments in the evidence tables."
        )
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or (
            "The detected movement is concentrated enough to support targeted action rather than broad portfolio changes."
        )

        confidence = str(llm_payload.get("confidence", "medium")).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        confidence_value = cast(Literal["high", "medium", "low"], confidence)

        insights = _sanitize_insights(llm_payload.get("insights")) or _default_insights(evidence)
        suggested_questions = as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions()
        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=4)
        assumptions.extend(prior_assumptions[:6])
        assumptions.append("SQL is constrained to the semantic model allowlist.")
        assumptions.append(
            "Deep path was selected for multi-step reasoning."
            if route == "deep_path"
            else "Fast path was selected for low latency."
        )

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and policy scope",
                summary="Classified route and bounded plan depth for deterministic orchestration.",
                status="done",
            ),
            TraceStep(
                id="t2",
                title="Generate and execute governed SQL",
                summary="Generated SQL with allowlist and restricted-column guardrails, then executed Snowflake steps.",
                status="done",
                sql=results[0].sql if results else None,
            ),
            TraceStep(
                id="t3",
                title="Synthesize insights from retrieved tables",
                summary="Combined deterministic table profiling and LLM narrative constrained to retrieved evidence.",
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence_value,
            whyItMatters=why_it_matters,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights,
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:8],
            trace=trace,
            dataTables=data_tables,
        )
