from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from app.config import settings
from app.models import (
    AgentResponse,
    Insight,
    PresentationIntent,
    QueryPlanStep,
    ResponseAudit,
    ResponseData,
    ResponseSummary,
    ResponseVisualization,
    SqlExecutionResult,
    SummaryCard,
    TemporalScope,
    TraceStep,
)
from app.prompts.templates import response_prompt
from app.services.llm_json import as_string_list
from app.services.llm_trace import llm_trace_stage
from app.services.stages.data_summarizer_stage import DataSummarizerStage
from app.services.stages.synthesis_stage_common import _ordered_assumptions
from app.services.stages.synthesis_stage_context import (
    _CONTEXT_COMPARISON_CAP,
    _CONTEXT_FACT_CAP,
    _build_claim_coverage,
    _build_data_quality,
    _build_observations,
    _build_series,
    _claim_support,
    _context_payload_for_prompt,
    _derive_evidence_status,
    _requested_claim_modes,
    _subtask_statuses,
    build_synthesis_context_package,
)
from app.services.stages.synthesis_stage_periods import _derive_period_bounds
from app.services.stages.synthesis_stage_response import (
    _attach_artifact_evidence,
    _default_questions,
    _deterministic_answer,
    _deterministic_headline,
    _deterministic_why_it_matters,
    _normalize_confidence,
    _sanitize_insights,
    _sanitize_summary_cards,
    build_incremental_answer_deltas,
)
from app.services.stages.synthesis_stage_visuals import (
    _enforce_multi_objective_rank_contract,
    _normalize_multi_objective_confidence_reason,
    _primary_visual_from_config,
    _resolve_visual_config,
)
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_fact_comparison_signals,
    build_metric_points,
    detect_grain_mismatch,
    results_to_data_tables,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json
        self._data_summarizer = DataSummarizerStage()

    async def build_response(
        self,
        *,
        message: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_interpretation_notes: list[str],
        prior_caveats: list[str],
        prior_assumptions: list[str],
        history: list[str],
        temporal_scope: TemporalScope | None = None,
    ) -> AgentResponse:
        evidence = build_evidence_rows(results, message=message)
        data_tables = results_to_data_tables(results)
        raw_artifacts = build_analysis_artifacts(results, message=message)
        facts, comparisons = build_fact_comparison_signals(results, message=message)
        artifacts = _attach_artifact_evidence(artifacts=raw_artifacts, facts=facts, comparisons=comparisons)
        table_summaries = self._data_summarizer.summarize_tables(results=results, message=message)
        subtask_status = _subtask_statuses(plan=plan, results=results, table_summaries=table_summaries)
        requested_claim_modes = _requested_claim_modes(
            message=message,
            presentation_intent=presentation_intent,
            step_count=max(len(plan or []), len(results)),
        )
        observations = _build_observations(data_tables)
        series = _build_series(data_tables)
        data_quality = _build_data_quality(
            data_tables=data_tables,
            table_summaries=table_summaries,
            subtask_status=subtask_status,
        )
        supported_claims, unsupported_claims = _build_claim_coverage(
            requested_modes=requested_claim_modes,
            data_tables=data_tables,
            artifacts=artifacts,
            series=series,
            facts=facts,
            comparisons=comparisons,
        )
        evidence_status, evidence_empty_reason = _derive_evidence_status(
            requested_claim_modes=requested_claim_modes,
            supported_claims=supported_claims,
            unsupported_claims=unsupported_claims,
            facts=facts,
            comparisons=comparisons,
            subtask_status=subtask_status,
        )
        headline, headline_refs = _deterministic_headline(facts=facts, comparisons=comparisons)
        claim_support = _claim_support(facts=facts, comparisons=comparisons)
        metrics = build_metric_points(results, evidence, message=message)
        synthesis_context = build_synthesis_context_package(
            plan=plan,
            results=results,
            table_summaries=table_summaries,
            artifacts=artifacts,
            requested_claim_modes=requested_claim_modes,
            supported_claims=supported_claims,
            unsupported_claims=unsupported_claims,
            observations=observations,
            series=series,
            data_quality=data_quality,
            facts=facts,
            comparisons=comparisons,
            evidence_status=evidence_status,
            evidence_empty_reason=evidence_empty_reason,
            subtask_status=subtask_status,
            interpretation_notes=prior_interpretation_notes,
            caveats=prior_caveats,
            headline=headline,
            headline_refs=headline_refs,
            message=message,
        )
        result_summary = _context_payload_for_prompt(synthesis_context, artifacts=artifacts)

        llm_payload: dict[str, Any] = {}
        try:
            system_prompt, user_prompt = response_prompt(
                message,
                json.dumps(presentation_intent.model_dump(), ensure_ascii=True),
                result_summary,
                history,
            )
            with llm_trace_stage("synthesis_final", {"planStepCount": len(plan or []), "historyDepth": len(history)}):
                llm_payload = await self._ask_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=settings.real_llm_max_tokens,
                )
        except Exception:
            if settings.provider_mode in {"sandbox", "prod", "prod-sandbox"}:
                raise
            llm_payload = {}

        total_rows = sum(result.rowCount for result in results)
        answer = str(llm_payload.get("answer", "")).strip() or _deterministic_answer(total_rows)
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or _deterministic_why_it_matters()
        confidence = _normalize_confidence(str(llm_payload.get("confidence", "medium")))
        confidence_reason = str(llm_payload.get("confidenceReason", "")).strip() or why_it_matters

        chart_config, table_config, _visual_issues = _resolve_visual_config(
            llm_payload=llm_payload,
            presentation_intent=presentation_intent,
            data_tables=data_tables,
        )
        _enforce_multi_objective_rank_contract(
            data_tables=data_tables,
            table_config=table_config,
            presentation_intent=presentation_intent,
        )
        confidence_reason = _normalize_multi_objective_confidence_reason(
            confidence_reason=confidence_reason,
            presentation_intent=presentation_intent,
            data_tables=data_tables,
            table_config=table_config,
        )
        period_bounds = _derive_period_bounds(message=message, results=results, temporal_scope=temporal_scope)

        insights = _sanitize_insights(llm_payload.get("insights")) or [
            Insight(
                id="i1",
                title="Primary data is ready",
                detail="Tabular evidence is available for inspection and export.",
                importance="medium",
            )
        ]
        summary_cards = _sanitize_summary_cards(llm_payload.get("summaryCards"))
        if not summary_cards:
            summary_cards = [
                SummaryCard(label=metric.label, value=f"{metric.value:,.2f}" if metric.unit != "count" else f"{metric.value:,.0f}")
                for metric in metrics[:3]
            ]
        suggested_questions = as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions(artifacts)
        assumptions = _ordered_assumptions(
            interpretation_notes=prior_interpretation_notes,
            caveats=prior_caveats,
            llm_assumptions=as_string_list(llm_payload.get("assumptions"), max_items=5),
            fallback_assumptions=prior_assumptions,
        )

        grain_mismatch = detect_grain_mismatch(results, message)
        if grain_mismatch and confidence == "high":
            confidence = "medium"

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and presentation path",
                summary="Validated relevance and generated a bounded delegation plan with presentation intent.",
                status="done",
            ),
            TraceStep(
                id="t2",
                title="Generate and execute governed SQL",
                summary="Generated SQL with allowlist and restricted-column guardrails, then executed warehouse steps.",
                status="done",
                sql=results[0].sql if results else None,
            ),
            TraceStep(
                id="t3",
                title="Synthesize narrative and visual config",
                summary="Combined deterministic summaries with constrained narrative synthesis and validated visual config.",
                status="done",
            ),
        ]

        return AgentResponse(
            summary=ResponseSummary(
                answer=answer,
                confidence=confidence,
                confidenceReason=confidence_reason,
                whyItMatters=why_it_matters,
                summaryCards=summary_cards,
                insights=insights[:4],
                suggestedQuestions=suggested_questions,
                assumptions=assumptions[:5],
                periodStart=period_bounds[0] if period_bounds else None,
                periodEnd=period_bounds[1] if period_bounds else None,
                periodLabel=period_bounds[2] if period_bounds else None,
            ),
            visualization=ResponseVisualization(
                chartConfig=chart_config,
                tableConfig=table_config,
                primaryVisual=_primary_visual_from_config(chart_config, table_config),
            ),
            data=ResponseData(
                dataTables=data_tables,
                evidence=evidence[:10],
                comparisons=comparisons[:_CONTEXT_COMPARISON_CAP],
            ),
            audit=ResponseAudit(
                presentationIntent=presentation_intent,
                artifacts=artifacts,
                facts=facts[:_CONTEXT_FACT_CAP],
                evidenceStatus=evidence_status,
                evidenceEmptyReason=evidence_empty_reason,
                subtaskStatus=subtask_status,
                claimSupport=claim_support[:40],
                headline=headline,
                headlineEvidenceRefs=headline_refs,
            ),
            trace=trace,
        )


__all__ = ["SynthesisStage", "build_incremental_answer_deltas"]
