from __future__ import annotations

from app.services.semantic_model import SemanticModel, semantic_model_summary


def route_prompt(user_message: str, history: list[str]) -> tuple[str, str]:
    history_text = "\n".join(f"- {item}" for item in history[-6:]) or "- none"
    system = (
        "You are a routing model for a governed customer-insights analytics assistant. "
        "Choose fast_path for simple metric retrieval and deep_path for multi-step causal analysis. "
        "Return strict JSON only."
    )
    user = (
        f"Conversation history:\n{history_text}\n\n"
        f"User question:\n{user_message}\n\n"
        'Return JSON with keys: {"route":"fast_path|deep_path","reason":"short string"}'
    )
    return system, user


def plan_prompt(user_message: str, route: str, model: SemanticModel, max_steps: int) -> tuple[str, str]:
    system = (
        "You design deterministic analytics plans with bounded steps for regulated environments. "
        "Use only entities from the semantic model. Return strict JSON only."
    )
    user = (
        f"{semantic_model_summary(model)}\n\n"
        f"Route: {route}\n"
        f"Max steps: {max_steps}\n"
        f"Question: {user_message}\n\n"
        "Return JSON with key `steps` as an array of objects. "
        'Each step object must include: {"goal":"string","primaryMetric":"string","grain":"string","timeWindow":"string"}'
    )
    return system, user


def sql_prompt(
    user_message: str,
    route: str,
    step_id: str,
    step_goal: str,
    model: SemanticModel,
    prior_sql: list[str],
) -> tuple[str, str]:
    prior_text = "\n".join(f"- {sql}" for sql in prior_sql[-3:]) or "- none"
    system = (
        "You are a SQL generator for Snowflake Cortex Analyst in a bank. "
        "Return one read-only SELECT statement compatible with Snowflake SQL. "
        "Use only allowlisted tables and no restricted columns. Return strict JSON only."
    )
    user = (
        f"{semantic_model_summary(model)}\n\n"
        f"Question: {user_message}\n"
        f"Route: {route}\n"
        f"Step id: {step_id}\n"
        f"Step goal: {step_goal}\n"
        f"Prior SQL in this turn:\n{prior_text}\n\n"
        "Output JSON keys:\n"
        '- "sql": string\n'
        '- "rationale": string\n'
        '- "assumptions": array of strings'
    )
    return system, user


def response_prompt(
    user_message: str,
    route: str,
    result_summary: str,
    evidence_summary: str,
) -> tuple[str, str]:
    system = (
        "You are an executive analytics narrator for a banking customer-insights platform. "
        "Write concise, high-signal output grounded only in supplied data summaries. "
        "Do not invent facts. Return strict JSON only."
    )
    user = (
        f"Question: {user_message}\n"
        f"Route: {route}\n\n"
        f"SQL result summary:\n{result_summary}\n\n"
        f"Evidence summary:\n{evidence_summary}\n\n"
        "Return JSON with keys:\n"
        '- "answer": concise direct answer\n'
        '- "whyItMatters": concise impact statement\n'
        '- "confidence": one of high|medium|low\n'
        '- "insights": array of up to 4 objects with keys {title,detail,importance(high|medium)}\n'
        '- "suggestedQuestions": array of 3 strings\n'
        '- "assumptions": array of up to 4 strings'
    )
    return system, user
