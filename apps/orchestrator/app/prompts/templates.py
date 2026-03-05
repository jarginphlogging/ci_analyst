from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from typing import Any

from app.config import settings
from app.services.semantic_model import SemanticModel, semantic_model_summary
from app.services.semantic_model_yaml import load_semantic_model_yaml

_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parent / "markdown"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def _load_prompt_template(name: str) -> str:
    path = _PROMPT_TEMPLATE_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def _render_prompt_template(name: str, *, values: dict[str, str]) -> str:
    rendered = _load_prompt_template(name)
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)

    remaining = sorted(set(_PLACEHOLDER_PATTERN.findall(rendered)))
    if remaining:
        missing = ", ".join(remaining)
        raise ValueError(f"Prompt template '{name}' has unresolved placeholders: {missing}")
    return rendered


def _history_text(history: list[str]) -> str:
    recent = [item.strip() for item in history[-6:] if item and item.strip()]
    return "\n".join(f"- {item}" for item in recent) or "- none"


def _retry_feedback_text(retry_feedback: list[dict[str, Any]] | None) -> str:
    if not retry_feedback:
        return "- none"

    lines: list[str] = []
    for item in retry_feedback[-2:]:
        if not isinstance(item, dict):
            continue
        if str(item.get("phase", "")).strip() != "sql_execution":
            continue
        attempt = int(item.get("attempt", 0) or 0)
        error = " ".join(str(item.get("error", "")).split()).strip()
        raw_failed_sql = item.get("failedSql")
        failed_sql = " ".join(raw_failed_sql.split()) if isinstance(raw_failed_sql, str) else ""
        if len(failed_sql) > 320:
            failed_sql = f"{failed_sql[:317]}..."
        parts = [f"- attempt {attempt}"]
        if error:
            parts.append(f"warehouse_error: {error}")
        if failed_sql:
            parts.append(f"failed_sql: {failed_sql}")
        lines.append("; ".join(parts))
    if not lines:
        return "- none"
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _full_semantic_model_yaml_text() -> str:
    return load_semantic_model_yaml().raw_text.strip()


def plan_prompt(
    user_message: str,
    semantic_model_summary_text: str,
    max_steps: int,
    history: list[str],
) -> tuple[str, str]:
    system = _render_prompt_template("planner_system", values={})
    user = _render_prompt_template(
        "planner_user",
        values={
            "history": _history_text(history),
            "semantic_model_summary": semantic_model_summary_text,
            "max_steps": str(max_steps),
            "user_message": user_message,
        },
    )
    return system, user


def sql_prompt(
    user_message: str,
    step_id: str,
    step_goal: str,
    model: SemanticModel,
    prior_sql: list[str],
    history: list[str],
    retry_feedback: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    prior_text = "\n".join(f"- {sql}" for sql in prior_sql[-3:]) or "- none"
    retry_text = _retry_feedback_text(retry_feedback)
    mode = settings.provider_mode
    execution_target = "configured SQL warehouse"
    dialect_rules = (
        "- Use the warehouse dialect shown above.\n"
        "- Treat retry feedback syntax errors as hard constraints and avoid repeating the same syntax family."
    )
    if mode == "sandbox":
        execution_target = "SQLite sandbox warehouse"
        dialect_rules = (
            "- Use SQLite-compatible SQL.\n"
            "- Use CURRENT_DATE without parentheses.\n"
            "- For date math/truncation in sandbox, use DATEADD('year'|'month'|'day', amount, date_value) and "
            "DATE_TRUNC('year'|'month'|'day', date_value).\n"
            "- Do not use DATE_ADD(... INTERVAL ...), INTERVAL literals, or CURRENT_DATE()."
        )
    elif mode == "prod":
        execution_target = "Snowflake warehouse"
        dialect_rules = (
            "- Use Snowflake SQL dialect.\n"
            "- Use retry feedback syntax errors as hard constraints and avoid equivalent rewrites that keep the same "
            "invalid construct."
        )

    system = _render_prompt_template("sql_system", values={})
    user = _render_prompt_template(
        "sql_user",
        values={
            "history": _history_text(history),
            "semantic_model_yaml": _full_semantic_model_yaml_text(),
            "user_message": user_message,
            "step_id": step_id,
            "step_goal": step_goal,
            "execution_target": execution_target,
            "dialect_rules": dialect_rules,
            "prior_sql": prior_text,
            "retry_feedback": retry_text,
        },
    )
    return system, user


def response_prompt(
    user_message: str,
    presentation_intent: str,
    result_summary: str,
    history: list[str],
) -> tuple[str, str]:
    system = _render_prompt_template("synthesis_system", values={})
    user = _render_prompt_template(
        "synthesis_user",
        values={
            "history": _history_text(history),
            "user_message": user_message,
            "presentation_intent": presentation_intent,
            "result_summary": result_summary,
        },
    )
    return system, user
