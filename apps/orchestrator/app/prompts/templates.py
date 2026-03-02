from __future__ import annotations

import json

from typing import Any

from app.services.semantic_model import SemanticModel, semantic_model_summary


def _history_text(history: list[str]) -> str:
    recent = [item.strip() for item in history[-6:] if item and item.strip()]
    return "\n".join(f"- {item}" for item in recent) or "- none"


def _retry_feedback_text(retry_feedback: list[dict[str, Any]] | None) -> str:
    if not retry_feedback:
        return "- none"

    def _compact(value: Any, *, max_chars: int = 240) -> str:
        text = " ".join(str(value).split())
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 3]}..."

    cleaned: list[dict[str, Any]] = []
    for item in retry_feedback[-3:]:
        if not isinstance(item, dict):
            continue
        preview: dict[str, Any] = {}
        for key in (
            "phase",
            "attempt",
            "stepId",
            "provider",
            "error",
            "failedSql",
            "clarificationQuestion",
            "notRelevantReason",
        ):
            value = item.get(key)
            if value in (None, ""):
                continue
            preview[key] = _compact(value, max_chars=320 if key == "failedSql" else 200)
        if preview:
            cleaned.append(preview)
    if not cleaned:
        return "- none"
    return json.dumps(cleaned, ensure_ascii=True, indent=2)


def plan_prompt(
    user_message: str,
    planner_scope_context: str,
    max_steps: int,
    history: list[str],
) -> tuple[str, str]:
    system = (
        "You are a relevance-and-delegation planner for Customer Insights analytics. "
        "Your sub-analysts are Snowflake Cortex Analysts (SCA) who are experts in the data domain. "
        "Your job is only to decide relevance and produce independent delegation tasks. "
        "Do not solve the analysis yourself and do not write SQL. "
        "Also determine a presentation intent for the final user-facing response. "
        "Break in-domain requests into the minimum number of independent tasks for parallel SCA execution. "
        "Each task must include enough business context for SCA to act without follow-up. "
        "Return strict JSON only."
    )
    user = (
        f"Conversation history:\n{_history_text(history)}\n\n"
        f"{planner_scope_context}\n\n"
        f"Max steps: {max_steps}\n"
        f"Question: {user_message}\n\n"
        "Return JSON with keys:\n"
        '- "relevance": one of in_domain|out_of_domain|unclear\n'
        '- "relevanceReason": short string\n'
        '- "presentationIntent": object with keys {displayType,chartType,tableStyle,rationale}\n'
        '- "tooComplex": boolean (true only if minimum independent decomposition requires more than max steps)\n'
        '- "tasks": array of objects (empty when relevance=out_of_domain or tooComplex=true)\n'
        'For presentationIntent: displayType is one of inline|table|chart. '
        'chartType is one of line|bar|stacked_bar|grouped_bar (only when displayType=chart). '
        'tableStyle is one of simple|ranked|comparison (only when displayType=table).\n'
        'Each task object must include: {"task":"natural-language task with all context needed for an independent Snowflake Cortex Analyst"}\n'
        "Rules:\n"
        "- Use the minimum number of independent tasks.\n"
        "- If one task can answer the question, produce exactly one task.\n"
        "- Default to one task when requested outputs share the same business scope (same metric family, grain, and time window).\n"
        "- Split into multiple tasks only when a single readable output would be materially worse or impossible (for example: incompatible grains, incompatible windows, or fundamentally different analytical products).\n"
        "- When multiple views can be produced from one coherent output, keep them in one task and ask for a readable unified result.\n"
        "- Do not exceed Max steps.\n"
        "- If relevance is unclear, still produce a best-effort task plan.\n"
        "- For simple metric requests, preserve the user wording and avoid rephrasing into implementation details.\n"
        "- Each task should specify only requested objective, grain, metrics, time window, and comparison baseline when explicitly relevant.\n"
        "- Keep tasks independent; avoid cross-task dependencies unless unavoidable.\n"
        "- Do not write SQL. Write only executable analysis instructions for SCA.\n"
        "- Do not mention table names, column names, or semantic-model field names in tasks.\n"
        "- Do not add extra metrics, breakdowns, or comparisons not requested by the user.\n"
        "- Prefer task sets where each output table is meaningful on its own, not only after synthesis."
    )
    return system, user


def sql_prompt(
    user_message: str,
    route: str,
    step_id: str,
    step_goal: str,
    model: SemanticModel,
    prior_sql: list[str],
    history: list[str],
    retry_feedback: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    prior_text = "\n".join(f"- {sql}" for sql in prior_sql[-3:]) or "- none"
    retry_text = _retry_feedback_text(retry_feedback)
    system = (
        "You are a SQL generator sub-analyst for Snowflake Cortex Analyst in a bank. "
        "You can respond with one of three outcomes: sql_ready, clarification, or not_relevant. "
        "When sql_ready, return one read-only SELECT statement compatible with Snowflake SQL. "
        "Use only allowlisted tables and no restricted columns. Return strict JSON only."
    )
    user = (
        f"Conversation history:\n{_history_text(history)}\n\n"
        f"{semantic_model_summary(model)}\n\n"
        f"Question: {user_message}\n"
        f"Step id: {step_id}\n"
        f"Step goal: {step_goal}\n"
        f"Route: {route}\n"
        f"Prior SQL in this turn:\n{prior_text}\n\n"
        f"Retry feedback from prior attempts (use this to avoid repeating known failures):\n{retry_text}\n\n"
        "Output JSON keys:\n"
        '- "generationType": one of sql_ready|clarification|not_relevant\n'
        '- "sql": string (required when generationType=sql_ready)\n'
        '- "rationale": string\n'
        '- "clarificationQuestion": string (required when generationType=clarification)\n'
        '- "notRelevantReason": string (required when generationType=not_relevant)\n'
        '- "assumptions": array of strings'
    )
    return system, user


def response_prompt(
    user_message: str,
    route: str,
    presentation_intent: str,
    result_summary: str,
    evidence_summary: str,
    history: list[str],
) -> tuple[str, str]:
    system = (
        "You are an executive analytics narrator for a banking customer-insights platform. "
        "Write concise, high-signal output grounded only in supplied data summaries. "
        "The synthesis context includes the original query, planner tasks, executed SQL per step, and deterministic pandas-generated table summaries (not raw tables). "
        "Use the planner analysis type to shape summary cards and select a primary visual focus. "
        "Do not invent facts. Return strict JSON only."
    )
    user = (
        f"Conversation history:\n{_history_text(history)}\n\n"
        f"Question: {user_message}\n"
        f"Presentation intent: {presentation_intent}\n"
        "\n"
        f"Synthesis context package:\n{result_summary}\n\n"
        f"Evidence summary:\n{evidence_summary}\n\n"
        "Return JSON with keys:\n"
        '- "answer": concise direct answer\n'
        '- "whyItMatters": concise impact statement\n'
        '- "confidence": one of high|medium|low\n'
        '- "confidenceReason": concise rationale for the selected confidence level grounded in provided summaries\n'
        '- "summaryCards": array of 1-3 objects with keys {label,value,detail(optional)}\n'
        '- "chartConfig": object or null with keys {type,x,y,series,xLabel,yLabel,yFormat}\n'
        '- "tableConfig": object or null with keys {style,columns,sortBy,sortDir,showRank}\n'
        '- "insights": array of up to 4 objects with keys {title,detail,importance(high|medium)}\n'
        '- "suggestedQuestions": array of 3 strings\n'
        '- "assumptions": array of up to 5 high-value strings grounded in the provided analysis context; exclude internal pipeline/debug notes\n'
        "Visual rules:\n"
        "- Use chartConfig when a chart is meaningful for the intent and data shape.\n"
        "- Use tableConfig when a table is more readable or chart is not reliable.\n"
        "- Set chartConfig or tableConfig to null when not applicable.\n"
        "- Never reference columns that are not present in returned table summaries."
    )
    return system, user
