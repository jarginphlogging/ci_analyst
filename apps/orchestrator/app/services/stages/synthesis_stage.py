from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, cast

from app.config import settings
from app.models import (
    AnalysisType,
    AgentResponse,
    AnalysisArtifact,
    ArtifactKind,
    EvidenceRow,
    Insight,
    PrimaryVisual,
    QueryPlanStep,
    SummaryCard,
    SqlExecutionResult,
    SynthesisContextPackage,
    SynthesisExecutedStep,
    SynthesisPlanStep,
    SynthesisPortfolioSummary,
    SynthesisQueryContext,
    SynthesisVisualArtifact,
    TraceStep,
    VisualType,
)
from app.prompts.templates import response_prompt
from app.services.llm_trace import llm_trace_stage
from app.services.llm_json import as_string_list
from app.services.stages.data_summarizer_stage import DataSummarizerStage
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_metric_points,
    detect_grain_mismatch,
    results_to_data_tables,
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


def _sanitize_summary_cards(raw: Any) -> list[SummaryCard]:
    if not isinstance(raw, list):
        return []

    cards: list[SummaryCard] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw[:3]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        value = str(entry.get("value", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not label or not value:
            continue
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        cards.append(SummaryCard(label=label, value=value, detail=detail))
    return cards


INTENT_VISUAL_POLICY: dict[AnalysisType, tuple[VisualType, tuple[ArtifactKind, ...]]] = {
    "trend_over_time": ("trend", ("trend_breakdown",)),
    "ranking_top_n_bottom_n": ("ranking", ("ranking_breakdown",)),
    "comparison": ("comparison", ("comparison_breakdown", "delta_breakdown")),
    "composition_breakdown": ("ranking", ("ranking_breakdown", "comparison_breakdown")),
    "aggregation_summary_stats": ("snapshot", ()),
    "point_in_time_snapshot": ("snapshot", ()),
    "period_over_period_change": ("comparison", ("delta_breakdown", "comparison_breakdown")),
    "anomaly_outlier_detection": ("trend", ("trend_breakdown", "distribution_breakdown")),
    "drill_down_root_cause": ("comparison", ("comparison_breakdown", "delta_breakdown", "ranking_breakdown")),
    "correlation_relationship": ("comparison", ("comparison_breakdown", "distribution_breakdown")),
    "cohort_analysis": ("trend", ("trend_breakdown", "comparison_breakdown")),
    "distribution_histogram": ("distribution", ("distribution_breakdown",)),
    "forecasting_projection": ("trend", ("trend_breakdown",)),
    "threshold_filter_segmentation": ("table", ()),
    "cumulative_running_total": ("trend", ("trend_breakdown",)),
    "rate_ratio_efficiency": ("comparison", ("comparison_breakdown", "delta_breakdown")),
}


def _format_metric_value(metric: Any) -> str:
    value = _as_float(getattr(metric, "value", None))
    if value is None:
        return "-"
    unit = getattr(metric, "unit", "count")
    if unit == "usd":
        if abs(value) >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if abs(value) >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:,.2f}"
    if unit == "pct":
        pct = value * 100 if abs(value) <= 1 else value
        return f"{pct:.2f}%"
    if unit == "bps":
        return f"{value:.0f} bps"
    return f"{value:,.0f}"


def _fallback_summary_cards(metrics: list[Any]) -> list[SummaryCard]:
    cards: list[SummaryCard] = []
    seen_labels: set[str] = set()
    for metric in metrics:
        label = str(getattr(metric, "label", "")).strip()
        if not label or label.lower() == "rows retrieved":
            continue
        normalized = label.lower()
        if normalized in seen_labels:
            continue
        seen_labels.add(normalized)
        cards.append(SummaryCard(label=label, value=_format_metric_value(metric)))
        if len(cards) >= 3:
            break
    return cards


def _sanitize_primary_visual(raw: Any) -> PrimaryVisual | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title", "")).strip()
    description = str(raw.get("description", "")).strip()
    artifact_raw = str(raw.get("artifactKind", "")).strip()
    visual_type_raw = str(raw.get("visualType", "")).strip().lower()
    artifact_kind: ArtifactKind | None = None
    visual_type: VisualType = "snapshot"
    if artifact_raw in {
        "ranking_breakdown",
        "comparison_breakdown",
        "delta_breakdown",
        "trend_breakdown",
        "distribution_breakdown",
    }:
        artifact_kind = artifact_raw  # type: ignore[assignment]
    if visual_type_raw in {"trend", "ranking", "comparison", "distribution", "snapshot", "table"}:
        visual_type = cast(VisualType, visual_type_raw)
    if not title and not artifact_kind:
        return None
    return PrimaryVisual(
        title=title or "Primary visual",
        description=description,
        visualType=visual_type,
        artifactKind=artifact_kind,
    )


def _artifact_is_finished(artifact: AnalysisArtifact) -> bool:
    if not artifact.rows:
        return False
    if artifact.kind == "trend_breakdown":
        return len(artifact.rows) >= 2
    return True


def _first_artifact_by_kinds(
    artifacts: list[AnalysisArtifact],
    kinds: tuple[ArtifactKind, ...],
) -> AnalysisArtifact | None:
    for kind in kinds:
        for artifact in artifacts:
            if artifact.kind == kind and _artifact_is_finished(artifact):
                return artifact
    return None


def _default_visual_title(analysis_type: AnalysisType, visual_type: VisualType) -> str:
    labels = {
        "trend_over_time": "Trend Over Time",
        "ranking_top_n_bottom_n": "Ranking",
        "comparison": "Comparison",
        "composition_breakdown": "Composition Breakdown",
        "aggregation_summary_stats": "Summary Snapshot",
        "point_in_time_snapshot": "Point-in-Time Snapshot",
        "period_over_period_change": "Period-over-Period Change",
        "anomaly_outlier_detection": "Anomaly View",
        "drill_down_root_cause": "Root Cause Breakdown",
        "correlation_relationship": "Relationship View",
        "cohort_analysis": "Cohort View",
        "distribution_histogram": "Distribution",
        "forecasting_projection": "Projection Trend",
        "threshold_filter_segmentation": "Filtered Segment List",
        "cumulative_running_total": "Cumulative Trend",
        "rate_ratio_efficiency": "Rate and Ratio Comparison",
    }
    return labels.get(analysis_type, f"{visual_type.title()} View")


def _resolve_primary_visual(
    *,
    analysis_type: AnalysisType,
    llm_visual: PrimaryVisual | None,
    artifacts: list[AnalysisArtifact],
) -> PrimaryVisual:
    preferred_visual_type, preferred_kinds = INTENT_VISUAL_POLICY.get(analysis_type, ("snapshot", ()))

    chosen_artifact: AnalysisArtifact | None = None
    if llm_visual and llm_visual.artifactKind and llm_visual.artifactKind in preferred_kinds:
        candidate = next((artifact for artifact in artifacts if artifact.kind == llm_visual.artifactKind), None)
        if candidate and _artifact_is_finished(candidate):
            chosen_artifact = candidate
    if not chosen_artifact:
        chosen_artifact = _first_artifact_by_kinds(artifacts, preferred_kinds)

    visual_type = preferred_visual_type
    artifact_kind: ArtifactKind | None = chosen_artifact.kind if chosen_artifact else None
    if visual_type in {"trend", "ranking", "comparison", "distribution"} and not artifact_kind:
        if any(_artifact_is_finished(artifact) for artifact in artifacts):
            visual_type = "table"
        else:
            visual_type = "snapshot"

    title = ""
    if llm_visual and llm_visual.title.strip():
        title = llm_visual.title.strip()
    elif chosen_artifact:
        title = chosen_artifact.title
    if not title:
        title = _default_visual_title(analysis_type, visual_type)

    description = ""
    if llm_visual and llm_visual.description.strip():
        description = llm_visual.description.strip()
    elif chosen_artifact and chosen_artifact.description:
        description = chosen_artifact.description

    return PrimaryVisual(
        title=title,
        description=description,
        visualType=visual_type,
        artifactKind=artifact_kind if visual_type in {"trend", "ranking", "comparison", "distribution"} else None,
    )


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


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json
        self._data_summarizer = DataSummarizerStage()

    async def build_fast_response(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        analysis_type: AnalysisType,
        secondary_analysis_type: AnalysisType | None,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            plan=plan,
            analysis_type=analysis_type,
            secondary_analysis_type=secondary_analysis_type,
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
        plan: list[QueryPlanStep] | None,
        analysis_type: AnalysisType,
        secondary_analysis_type: AnalysisType | None,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            plan=plan,
            analysis_type=analysis_type,
            secondary_analysis_type=secondary_analysis_type,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=True,
        )

    def _synthesis_context_package(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        analysis_type: AnalysisType,
        secondary_analysis_type: AnalysisType | None,
        results: list[SqlExecutionResult],
        artifacts: list[AnalysisArtifact],
    ) -> SynthesisContextPackage:
        _ = route
        plan_steps = plan or []
        table_summaries = self._data_summarizer.summarize_tables(results=results, message=message)

        synthesis_plan = [
            SynthesisPlanStep(
                id=step.id,
                goal=step.goal,
                dependsOn=step.dependsOn,
                independent=step.independent,
            )
            for step in plan_steps
        ]

        executed_steps: list[SynthesisExecutedStep] = []
        for index, result in enumerate(results, start=1):
            step = plan_steps[index - 1] if index - 1 < len(plan_steps) else None
            table_summary = table_summaries[index - 1] if index - 1 < len(table_summaries) else {}
            plan_step = (
                SynthesisPlanStep(
                    id=step.id,
                    goal=step.goal,
                    dependsOn=step.dependsOn,
                    independent=step.independent,
                )
                if step
                else SynthesisPlanStep(
                    id=f"step_{index}",
                    goal="No explicit plan step was available.",
                    dependsOn=[],
                    independent=True,
                )
            )
            executed_steps.append(
                SynthesisExecutedStep(
                    stepIndex=index,
                    planStep=plan_step,
                    executedSql=result.sql,
                    rowCount=result.rowCount,
                    tableSummary=table_summary,
                )
            )

        return SynthesisContextPackage(
            queryContext=SynthesisQueryContext(
                originalUserQuery=message,
                route="standard",
                analysisType=analysis_type,
                secondaryAnalysisType=secondary_analysis_type,
            ),
            plan=synthesis_plan,
            executedSteps=executed_steps,
            availableVisualArtifacts=[
                SynthesisVisualArtifact(kind=artifact.kind, title=artifact.title, rowCount=len(artifact.rows))
                for artifact in artifacts
                if artifact.rows
            ],
            portfolioSummary=SynthesisPortfolioSummary(
                tableCount=len(results),
                totalRows=sum(result.rowCount for result in results),
            ),
        )

    async def _build_response(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        analysis_type: AnalysisType,
        secondary_analysis_type: AnalysisType | None,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
        with_llm: bool,
    ) -> AgentResponse:
        evidence = build_evidence_rows(results, message=message)
        artifacts = build_analysis_artifacts(results, message=message)
        metrics = build_metric_points(results, evidence, message=message)
        data_tables = results_to_data_tables(results)
        synthesis_context = self._synthesis_context_package(
            message=message,
            route=route,
            plan=plan,
            analysis_type=analysis_type,
            secondary_analysis_type=secondary_analysis_type,
            results=results,
            artifacts=artifacts,
        )
        result_summary = synthesis_context.model_dump_json()
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
                with llm_trace_stage(
                    "synthesis_final",
                    {
                        "planStepCount": len(plan or []),
                        "historyDepth": len(history),
                    },
                ):
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

        confidence_reason = str(llm_payload.get("confidenceReason", "")).strip()
        if not confidence_reason:
            llm_assumptions = as_string_list(llm_payload.get("assumptions"), max_items=1)
            if llm_assumptions:
                confidence_reason = llm_assumptions[0]
        if not confidence_reason:
            confidence_reason = str(llm_payload.get("whyItMatters", "")).strip()

        insights = _sanitize_insights(llm_payload.get("insights")) or _default_insights(evidence, artifacts)
        summary_cards = _sanitize_summary_cards(llm_payload.get("summaryCards")) or _fallback_summary_cards(metrics)
        primary_visual = _resolve_primary_visual(
            analysis_type=analysis_type,
            llm_visual=_sanitize_primary_visual(llm_payload.get("primaryVisual")),
            artifacts=artifacts,
        )
        suggested_questions = (
            as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions(artifacts)
        )
        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=4)
        assumptions.extend(prior_assumptions[:6])
        assumptions.append("SQL is constrained to the semantic model allowlist.")
        assumptions.append("Final synthesis used planner tasks, executed SQL, and deterministic table summaries.")
        assumptions.append("Standard execution pipeline was used.")

        if grain_mismatch:
            requested, detected = grain_mismatch
            assumptions.append(
                f"Requested grain ({requested}) differed from returned grain ({detected}); insights are based on returned grain."
            )

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and policy scope",
                summary="Validated relevance and generated a bounded delegation plan for deterministic orchestration.",
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
                    "Built deterministic summary modules from planner+SQL output."
                    if not with_llm
                    else "Combined planner context, executed SQL, and deterministic table summaries with constrained narrative synthesis."
                ),
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence,
            confidenceReason=confidence_reason,
            whyItMatters=why_it_matters,
            analysisType=analysis_type,
            secondaryAnalysisType=secondary_analysis_type,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights,
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:8],
            trace=trace,
            summaryCards=summary_cards,
            primaryVisual=primary_visual,
            dataTables=data_tables,
            artifacts=artifacts,
        )


def build_incremental_answer_deltas(fast_answer: str, final_answer: str) -> list[str]:
    _ = fast_answer
    final = final_answer.strip()
    if not final:
        return [""]
    return [f"{token} " for token in final.split(" ")]
