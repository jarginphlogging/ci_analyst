from __future__ import annotations

from typing import Any

from app.models import AgentResponse, SqlExecutionResult
from app.services.types import TurnExecutionContext


def preview_text(text: str, max_chars: int = 220) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 3]}..."


def history_summary(history: list[str]) -> dict[str, Any]:
    return {
        "historyDepth": len(history),
        "recentTurns": [preview_text(turn, max_chars=140) for turn in history[-3:]],
    }


def plan_summary(context: TurnExecutionContext) -> dict[str, Any]:
    return {
        "presentationIntent": context.presentation_intent.model_dump(),
        "stepCount": len(context.plan),
        "steps": [
            {
                "id": step.id,
                "goal": preview_text(step.goal, max_chars=180),
                "dependsOn": step.dependsOn,
                "independent": step.independent,
            }
            for step in context.plan
        ],
    }


def result_row_sample(row: dict[str, Any], max_columns: int = 8) -> dict[str, Any]:
    sampled: dict[str, Any] = {}
    column_items = list(row.items())[:max_columns]
    for key, value in column_items:
        if isinstance(value, str):
            sampled[key] = preview_text(value, max_chars=90)
        elif isinstance(value, (int, float, bool)) or value is None:
            sampled[key] = value
        else:
            sampled[key] = preview_text(str(value), max_chars=90)
    if len(row) > max_columns:
        sampled["__truncatedColumns"] = len(row) - max_columns
    return sampled


def results_summary(results: list[SqlExecutionResult]) -> dict[str, Any]:
    step_summaries = []
    for index, result in enumerate(results, start=1):
        sample_rows = [result_row_sample(row) for row in result.rows[:2]]
        column_count = len(result.rows[0]) if result.rows else 0
        step_summaries.append(
            {
                "stepIndex": index,
                "rowCount": result.rowCount,
                "columnCount": column_count,
                "sqlPreview": preview_text(result.sql, max_chars=260),
                "sampleRows": sample_rows,
            }
        )

    return {
        "queryCount": len(results),
        "totalRows": sum(result.rowCount for result in results),
        "steps": step_summaries,
    }


def response_summary(response: AgentResponse) -> dict[str, Any]:
    return {
        "presentationIntent": response.audit.presentationIntent.model_dump() if response.audit.presentationIntent else None,
        "chartConfig": response.visualization.chartConfig.model_dump() if response.visualization.chartConfig else None,
        "tableConfig": response.visualization.tableConfig.model_dump() if response.visualization.tableConfig else None,
        "confidence": response.summary.confidence,
        "answerPreview": preview_text(response.summary.answer, max_chars=260),
        "summaryCardLabels": [card.label for card in response.summary.summaryCards[:5]],
        "primaryVisual": response.visualization.primaryVisual.model_dump() if response.visualization.primaryVisual else None,
        "insightTitles": [insight.title for insight in response.summary.insights[:5]],
        "suggestedQuestions": response.summary.suggestedQuestions[:3],
        "tableCount": len(response.data.dataTables),
        "artifactCount": len(response.audit.artifacts),
    }


def deterministic_answer_fallback(response: AgentResponse) -> str:
    summary_bits: list[str] = []
    if response.summary.summaryCards:
        for card in response.summary.summaryCards[:3]:
            summary_bits.append(f"{card.label}: {card.value}")
    elif response.data.dataTables:
        summary_bits.append(f"Retrieved {len(response.data.dataTables)} table(s) for review.")
    if not summary_bits:
        summary_bits.append("Analysis completed. Review tables and trace for details.")
    return " | ".join(summary_bits)
