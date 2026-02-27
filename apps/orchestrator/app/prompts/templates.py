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
    analysis_taxonomy = (
        "trend_over_time, ranking_top_n_bottom_n, comparison, composition_breakdown, aggregation_summary_stats, "
        "point_in_time_snapshot, period_over_period_change, anomaly_outlier_detection, drill_down_root_cause, "
        "correlation_relationship, cohort_analysis, distribution_histogram, forecasting_projection, "
        "threshold_filter_segmentation, cumulative_running_total, rate_ratio_efficiency"
    )
    analysis_taxonomy_guidance = (
        "Analysis taxonomy guidance:\n"
        "- trend_over_time: How has X changed over period Y? Revenue by quarter, loan originations month-over-month, headcount growth year-over-year. "
        "Primary visual shape: time-ordered series.\n"
        "- ranking_top_n_bottom_n: Who are the top 10 clients by AUM? What are the worst-performing products? Which branches have the most delinquencies? "
        "Primary visual shape: ranked entities with metric values.\n"
        "- comparison: How does A compare to B? Region vs region, product vs product, this year vs last year, actuals vs budget/forecast. "
        "Primary visual shape: side-by-side groups/periods with deltas when relevant.\n"
        "- composition_breakdown: What makes up the whole? Revenue by business line, loan portfolio by risk rating, expenses by category. "
        "Primary visual shape: parts-of-whole breakdown.\n"
        "- aggregation_summary_stats: What is the total, average, median, count, min, max of X? "
        "Primary visual shape: compact KPI/snapshot summary.\n"
        "- point_in_time_snapshot: What is the current state of X? Outstanding balance right now, current headcount, today's pipeline value. "
        "Primary visual shape: as-of snapshot values.\n"
        "- period_over_period_change: Specifically about deltas: what is the MoM growth rate, QoQ change, YoY variance. "
        "Primary visual shape: prior vs current with change values/percent.\n"
        "- anomaly_outlier_detection: What looks unusual? Spikes, drops, values outside expected ranges. "
        "Primary visual shape: series/distribution highlighting outliers.\n"
        "- drill_down_root_cause: Why did X happen? Start at aggregate and decompose by dimensions to find the driver. "
        "Primary visual shape: ordered driver decomposition.\n"
        "- correlation_relationship: Does X move with Y? Is there a relationship between two measures? "
        "Primary visual shape: paired values suitable for relationship comparison.\n"
        "- cohort_analysis: How does group A (shared starting event/attribute) behave over time compared to group B? "
        "Primary visual shape: cohort by period matrix/series.\n"
        "- distribution_histogram: How is X spread across a population? "
        "Primary visual shape: buckets/percentiles/distribution summary.\n"
        "- forecasting_projection: What will X be in the future based on current trajectory? "
        "Primary visual shape: historical trend with projected periods.\n"
        "- threshold_filter_segmentation: Which records meet criteria X? "
        "Primary visual shape: filtered record list/table.\n"
        "- cumulative_running_total: How does X accumulate over time? YTD and running totals. "
        "Primary visual shape: time-ordered running total.\n"
        "- rate_ratio_efficiency: What is the conversion rate, utilization rate, cost per unit, or ratio of X to Y? "
        "Primary visual shape: ratio/rate comparisons by group or time."
    )
    system = (
        "You are a relevance-and-delegation planner for Customer Insights analytics. "
        "Your sub-analysts are Snowflake Cortex Analysts (SCA) who are experts in the data domain. "
        "Your job is only to decide relevance and produce independent delegation tasks. "
        "Do not solve the analysis yourself and do not write SQL. "
        "Break in-domain requests into the minimum number of independent tasks for parallel SCA execution. "
        "Each task must include enough business context for SCA to act without follow-up. "
        "Return strict JSON only."
    )
    user = (
        f"Conversation history:\n{_history_text(history)}\n\n"
        f"{planner_scope_context}\n\n"
        f"Max steps: {max_steps}\n"
        f"Question: {user_message}\n\n"
        f"{analysis_taxonomy_guidance}\n\n"
        "Return JSON with keys:\n"
        '- "relevance": one of in_domain|out_of_domain|unclear\n'
        '- "relevanceReason": short string\n'
        f'- "analysisType": one of {analysis_taxonomy}\n'
        '- "secondaryAnalysisType": optional one of the same taxonomy values (omit when not needed)\n'
        '- "tooComplex": boolean (true only if minimum independent decomposition requires more than max steps)\n'
        '- "tasks": array of objects (empty when relevance=out_of_domain or tooComplex=true)\n'
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
        "- Ensure at least one delegated task explicitly requests output shape suitable for the primary visual implied by analysisType.\n"
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
        "You can respond with one of four outcomes: sql_ready, clarification, technical_failure, or not_relevant. "
        "Use clarification only for genuine business ambiguity (missing metric, grain, or time window). "
        "Use technical_failure for SQL/compiler/runtime issues so the orchestrator can retry automatically. "
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
        '- "generationType": one of sql_ready|clarification|technical_failure|not_relevant\n'
        '- "sql": string (required when generationType=sql_ready)\n'
        '- "rationale": string\n'
        '- "clarificationQuestion": string (required when generationType=clarification)\n'
        '- "error": string (required when generationType=technical_failure; concise technical reason)\n'
        '- "notRelevantReason": string (required when generationType=not_relevant)\n'
        '- "assumptions": array of strings\n'
        "SQL quality rules:\n"
        "- For set operations (UNION/UNION ALL), ensure final ORDER BY uses projected output columns only.\n"
        "- Include deterministic tie-breakers in ORDER BY (for example, business key after metric sort).\n"
        "- If custom sort precedence is needed, project an explicit sort key in SELECT and order by that key."
    )
    return system, user


def response_prompt(
    user_message: str,
    route: str,
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
        "\n"
        f"Synthesis context package:\n{result_summary}\n\n"
        f"Evidence summary:\n{evidence_summary}\n\n"
        "Return JSON with keys:\n"
        '- "answer": concise direct answer\n'
        '- "whyItMatters": concise impact statement\n'
        '- "confidence": one of high|medium|low\n'
        '- "confidenceReason": concise rationale for the selected confidence level grounded in provided summaries\n'
        '- "summaryCards": array of 1-3 objects with keys {label,value,detail(optional)}\n'
        '- "primaryVisual": object with keys {title,description(optional),visualType(one of trend|ranking|comparison|distribution|snapshot|table),artifactKind(optional one of ranking_breakdown|comparison_breakdown|delta_breakdown|trend_breakdown|distribution_breakdown)}\n'
        '- "insights": array of up to 4 objects with keys {title,detail,importance(high|medium)}\n'
        '- "suggestedQuestions": array of 3 strings\n'
        '- "assumptions": array of up to 4 strings'
    )
    return system, user
