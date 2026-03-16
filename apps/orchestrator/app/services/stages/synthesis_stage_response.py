from __future__ import annotations

from typing import Any, Literal, cast

from app.models import AnalysisArtifact, ComparisonSignal, EvidenceReference, FactSignal, Insight, SummaryCard
from app.services.stages.synthesis_stage_common import _ordered_assumptions, _prettify


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
        items.append(Insight(id=f"i{index}", title=title, detail=detail, importance=normalized_importance))
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


def _normalize_confidence(raw_confidence: str) -> Literal["high", "medium", "low"]:
    confidence = raw_confidence.lower().strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return cast(Literal["high", "medium", "low"], confidence)


def _default_questions(artifacts: list[AnalysisArtifact]) -> list[str]:
    if any(artifact.kind == "ranking_breakdown" for artifact in artifacts):
        return [
            "Can you break the top entities down by channel?",
            "Which entities moved most versus prior period?",
            "What percentage of total comes from the top decile?",
        ]
    if any(artifact.kind == "trend_breakdown" for artifact in artifacts):
        return [
            "Which segments are driving this trend?",
            "How does this compare to the same period last year?",
            "Where are change points or anomalies?",
        ]
    return [
        "Can you break this down by state and channel?",
        "How does this compare to the previous period?",
        "Which segments are driving the result?",
    ]


def _deterministic_answer(results_row_count: int) -> str:
    if results_row_count <= 0:
        return "I completed the governed pipeline but no usable rows were returned."
    return f"I retrieved {results_row_count} rows and prepared a governed summary with visual-ready data."


def _deterministic_why_it_matters() -> str:
    return "Insights are grounded in the retrieved SQL output, and visuals are validated before rendering."


def _deterministic_headline(
    *,
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> tuple[str, list[EvidenceReference]]:
    if comparisons:
        top = comparisons[0]
        pct_text = f" ({top.pctDelta:+.1f}%)" if top.pctDelta is not None else ""
        text = (
            f"{_prettify(top.metric)} moved {top.absDelta:+,.2f}{pct_text}, "
            f"from {top.priorValue:,.2f} in {top.priorPeriod} to {top.currentValue:,.2f} in {top.currentPeriod}."
        )
        return text, [EvidenceReference(refType="comparison", refId=top.id)]
    if facts:
        top = facts[0]
        text = f"{_prettify(top.metric)} is {top.value:,.2f} for {top.period}."
        return text, [EvidenceReference(refType="fact", refId=top.id)]
    return "", []


def _attach_artifact_evidence(
    *,
    artifacts: list[AnalysisArtifact],
    facts: list[FactSignal],
    comparisons: list[ComparisonSignal],
) -> list[AnalysisArtifact]:
    fact_by_metric: dict[str, list[FactSignal]] = {}
    for fact in facts:
        fact_by_metric.setdefault(fact.metric.lower(), []).append(fact)
    comparison_by_metric: dict[str, list[ComparisonSignal]] = {}
    for comparison in comparisons:
        comparison_by_metric.setdefault(comparison.metric.lower(), []).append(comparison)

    enriched: list[AnalysisArtifact] = []
    for artifact in artifacts:
        refs: list[EvidenceReference] = []
        if artifact.kind == "comparison_breakdown":
            dimension_key = artifact.dimensionKey or "metric"
            for row in artifact.rows[:8]:
                token = str(row.get(dimension_key, "")).strip().lower()
                for comparison in comparison_by_metric.get(token, [])[:2]:
                    refs.append(EvidenceReference(refType="comparison", refId=comparison.id))
        if not refs and artifact.valueKey:
            for fact in fact_by_metric.get(artifact.valueKey.lower(), [])[:2]:
                refs.append(EvidenceReference(refType="fact", refId=fact.id))
        if not refs and comparisons:
            refs.append(EvidenceReference(refType="comparison", refId=comparisons[0].id))
        if not refs and facts:
            refs.append(EvidenceReference(refType="fact", refId=facts[0].id))

        best_score = 0.0
        best_rank: int | None = None
        best_driver = None
        best_support = None
        for ref in refs:
            if ref.refType == "fact":
                source = next((item for item in facts if item.id == ref.refId), None)
            else:
                source = next((item for item in comparisons if item.id == ref.refId), None)
            if source is None:
                continue
            score = float(getattr(source, "salienceScore", 0.0) or 0.0)
            if score >= best_score:
                best_score = score
                best_rank = getattr(source, "salienceRank", None)
                best_driver = getattr(source, "salienceDriver", None)
                best_support = getattr(source, "supportStatus", None)

        enriched.append(
            artifact.model_copy(
                update={
                    "evidenceRefs": refs[:6],
                    "salienceScore": round(best_score, 6) if best_score else None,
                    "salienceRank": best_rank,
                    "salienceDriver": best_driver,
                    "supportStatus": best_support,
                }
            )
        )
    return enriched


def build_incremental_answer_deltas(answer: str) -> list[str]:
    final = answer.strip()
    if not final:
        return [""]
    return [f"{token} " for token in final.split(" ")]


__all__ = [
    "_attach_artifact_evidence",
    "_default_questions",
    "_deterministic_answer",
    "_deterministic_headline",
    "_deterministic_why_it_matters",
    "_normalize_confidence",
    "_ordered_assumptions",
    "_sanitize_insights",
    "_sanitize_summary_cards",
    "build_incremental_answer_deltas",
]
