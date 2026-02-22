from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, cast

from app.config import settings
from app.models import AgentResponse, AnalysisArtifact, EvidenceRow, Insight, SqlExecutionResult, TraceStep
from app.prompts.templates import response_prompt
from app.services.llm_json import as_string_list
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_metric_points,
    detect_grain_mismatch,
    results_to_data_tables,
    summarize_results_for_prompt,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


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


def _artifact_by_kind(artifacts: list[AnalysisArtifact], *kinds: str) -> AnalysisArtifact | None:
    for artifact in artifacts:
        if artifact.kind in kinds:
            return artifact
    return None


def _default_insights(evidence: list[EvidenceRow], artifacts: list[AnalysisArtifact]) -> list[Insight]:
    ranking = _artifact_by_kind(artifacts, "ranking_breakdown")
    if ranking and ranking.rows:
        dimension_key = ranking.dimensionKey or ranking.columns[1]
        value_key = ranking.valueKey or ranking.columns[2]
        top = ranking.rows[0]
        top_label = str(top.get(dimension_key, "Top segment"))
        top_value = _as_float(top.get(value_key))
        top_value_text = f"{top_value:,.2f}" if top_value is not None else "N/A"
        top3 = ranking.rows[:3]
        top3_share = sum(_as_float(row.get("share_pct")) or 0.0 for row in top3)
        return [
            Insight(
                id="i1",
                title=f"{top_label} leads the portfolio",
                detail=f"Top entity volume is {top_value_text} in the retrieved result set.",
                importance="high",
            ),
            Insight(
                id="i2",
                title="Concentration is measurable",
                detail=f"Top three entities account for approximately {top3_share:.1f}% of total volume.",
                importance="medium",
            ),
        ]

    comparison = _artifact_by_kind(artifacts, "comparison_breakdown", "delta_breakdown")
    if comparison and comparison.rows:
        dimension_key = comparison.dimensionKey or comparison.columns[0]
        top = max(
            comparison.rows,
            key=lambda row: abs(_as_float(row.get("change_value")) or 0.0),
        )
        mover = str(top.get(dimension_key, "Segment"))
        change_value = _as_float(top.get("change_value")) or 0.0
        change_pct = _as_float(top.get("change_pct"))
        pct_text = f" ({change_pct:+.1f}%)" if change_pct is not None else ""
        return [
            Insight(
                id="i1",
                title=f"Largest move: {mover}",
                detail=f"Current versus prior delta is {change_value:+,.2f}{pct_text}.",
                importance="high",
            ),
            Insight(
                id="i2",
                title="Comparative movement available",
                detail="Segment-level prior/current deltas are available for intervention prioritization.",
                importance="medium",
            ),
        ]

    trend = _artifact_by_kind(artifacts, "trend_breakdown")
    if trend and len(trend.rows) >= 2:
        value_key = trend.valueKey or trend.columns[1]
        first = _as_float(trend.rows[0].get(value_key))
        last = _as_float(trend.rows[-1].get(value_key))
        if first is not None and last is not None:
            direction = "up" if last >= first else "down"
            delta = last - first
            return [
                Insight(
                    id="i1",
                    title=f"Trend is {direction}",
                    detail=f"The series moved by {delta:+,.2f} from first to latest observed period.",
                    importance="high",
                ),
                Insight(
                    id="i2",
                    title="Time-series evidence is available",
                    detail="Trend artifact supports period-by-period validation and follow-up decomposition.",
                    importance="medium",
                ),
            ]

    distribution = _artifact_by_kind(artifacts, "distribution_breakdown")
    if distribution and distribution.rows:
        p90 = next((row for row in distribution.rows if str(row.get("stat")) == "p90"), None)
        median = next((row for row in distribution.rows if str(row.get("stat")) == "median"), None)
        if p90 and median:
            p90_value = _as_float(p90.get("value")) or 0.0
            median_value = _as_float(median.get("value")) or 0.0
            spread = p90_value - median_value
            return [
                Insight(
                    id="i1",
                    title="Upper-tail spread is visible",
                    detail=f"P90 exceeds median by {spread:,.2f}, indicating concentration in the upper segment.",
                    importance="high",
                )
            ]

    if evidence:
        top = max(evidence, key=lambda row: abs(row.changeBps))
        return [
            Insight(
                id="i1",
                title=f"Largest movement in {top.segment}",
                detail=f"Segment change of {top.changeBps:.1f} dominates the observed shift.",
                importance="high",
            )
        ]

    return [
        Insight(
            id="i1",
            title="Primary data is ready",
            detail="Tabular evidence is available for inspection and export.",
            importance="medium",
        )
    ]


def _default_questions(artifacts: list[AnalysisArtifact]) -> list[str]:
    if _artifact_by_kind(artifacts, "ranking_breakdown"):
        return [
            "Can you break the top entities down by channel?",
            "Which entities moved most versus prior period?",
            "What percentage of total comes from the top decile?",
        ]
    if _artifact_by_kind(artifacts, "trend_breakdown"):
        return [
            "Which segments are driving this trend?",
            "How does this compare to the same period last year?",
            "Where are change points or anomalies?",
        ]
    if _artifact_by_kind(artifacts, "comparison_breakdown", "delta_breakdown"):
        return [
            "What explains the largest positive and negative movers?",
            "Can you show this by state and channel?",
            "Which drivers are persistent versus one-off?",
        ]
    return [
        "Can you break this down by state and channel?",
        "How does this compare to the previous period?",
        "Which segments are driving the result?",
    ]


def _deterministic_answer(message: str, artifacts: list[AnalysisArtifact], results: list[SqlExecutionResult]) -> str:
    ranking = _artifact_by_kind(artifacts, "ranking_breakdown")
    if ranking and ranking.rows:
        dimension_key = ranking.dimensionKey or ranking.columns[1]
        value_key = ranking.valueKey or ranking.columns[2]
        top_rows = ranking.rows[:3]
        snippets: list[str] = []
        for row in top_rows:
            label = str(row.get(dimension_key, "unknown"))
            value = _as_float(row.get(value_key))
            if value is None:
                continue
            snippets.append(f"{label} ({value:,.2f})")
        if snippets:
            return f"Top results are {', '.join(snippets)}."

    comparison = _artifact_by_kind(artifacts, "comparison_breakdown", "delta_breakdown")
    if comparison and comparison.rows:
        dimension_key = comparison.dimensionKey or comparison.columns[0]
        top = max(comparison.rows, key=lambda row: abs(_as_float(row.get("change_value")) or 0.0))
        mover = str(top.get(dimension_key, "segment"))
        delta = _as_float(top.get("change_value"))
        if delta is not None:
            return f"Largest comparative movement is in {mover} with a change of {delta:+,.2f}."

    trend = _artifact_by_kind(artifacts, "trend_breakdown")
    if trend and len(trend.rows) >= 2:
        value_key = trend.valueKey or trend.columns[1]
        first = _as_float(trend.rows[0].get(value_key))
        last = _as_float(trend.rows[-1].get(value_key))
        if first is not None and last is not None:
            return f"The observed trend moved from {first:,.2f} to {last:,.2f}."

    if results:
        total_rows = sum(result.rowCount for result in results)
        return f"I retrieved {total_rows} rows and prepared exportable tables plus a prioritized insight summary."
    return "I completed the governed pipeline but no usable rows were returned."


def _deterministic_why_it_matters() -> str:
    return "Insights are grounded in the exact retrieved tables, which are available for inspection and export."


def _normalize_confidence(raw_confidence: str) -> Literal["high", "medium", "low"]:
    confidence = raw_confidence.lower().strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return cast(Literal["high", "medium", "low"], confidence)


def _answer_delta_tail(fast_answer: str, final_answer: str) -> str:
    fast = fast_answer.strip()
    final = final_answer.strip()
    if final.startswith(fast):
        return final[len(fast) :].strip()
    return final


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json

    async def build_fast_response(
        self,
        *,
        message: str,
        route: str,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=False,
        )

    async def build_response(
        self,
        *,
        message: str,
        route: str,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=True,
        )

    async def _build_response(
        self,
        *,
        message: str,
        route: str,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
        with_llm: bool,
    ) -> AgentResponse:
        evidence = build_evidence_rows(results, message=message)
        artifacts = build_analysis_artifacts(results, message=message)
        metrics = build_metric_points(results, evidence, message=message)
        data_tables = results_to_data_tables(results)
        result_summary = summarize_results_for_prompt(results)
        evidence_summary = str([row.model_dump() for row in evidence[:8]])

        llm_payload: dict[str, Any] = {}
        if with_llm:
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

        answer = str(llm_payload.get("answer", "")).strip() or _deterministic_answer(message, artifacts, results)
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or _deterministic_why_it_matters()
        confidence_default = "medium" if with_llm else "high"
        confidence = _normalize_confidence(str(llm_payload.get("confidence", confidence_default)))

        grain_mismatch = detect_grain_mismatch(results, message)
        if grain_mismatch and confidence == "high":
            confidence = "medium"

        insights = _sanitize_insights(llm_payload.get("insights")) or _default_insights(evidence, artifacts)
        suggested_questions = (
            as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions(artifacts)
        )
        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=4)
        assumptions.extend(prior_assumptions[:6])
        assumptions.append("SQL is constrained to the semantic model allowlist.")
        assumptions.append(
            "Deep path was selected for multi-step reasoning." if route == "deep_path" else "Fast path was selected for low latency."
        )

        if grain_mismatch:
            requested, detected = grain_mismatch
            assumptions.append(
                f"Requested grain ({requested}) differed from returned grain ({detected}); insights are based on returned grain."
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
                title="Profile results and render adaptive insight modules",
                summary=(
                    "Built deterministic insights and modules from result shape."
                    if not with_llm
                    else "Combined deterministic result profiling with LLM narrative constrained to retrieved evidence."
                ),
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence,
            whyItMatters=why_it_matters,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights,
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:8],
            trace=trace,
            dataTables=data_tables,
            artifacts=artifacts,
        )


def build_incremental_answer_deltas(fast_answer: str, final_answer: str) -> list[str]:
    _ = fast_answer
    final = final_answer.strip()
    if not final:
        return [""]
    return [f"{token} " for token in final.split(" ")]
