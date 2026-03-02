from __future__ import annotations

import json
import re
from pathlib import Path

from typing import Any

from app.services.semantic_model import SemanticModel, semantic_model_summary

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
    system = _render_prompt_template("planner_system", values={})
    user = _render_prompt_template(
        "planner_user",
        values={
            "history": _history_text(history),
            "planner_scope_context": planner_scope_context,
            "max_steps": str(max_steps),
            "user_message": user_message,
        },
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
    system = _render_prompt_template("sql_system", values={})
    user = _render_prompt_template(
        "sql_user",
        values={
            "history": _history_text(history),
            "semantic_model_summary": semantic_model_summary(model),
            "user_message": user_message,
            "step_id": step_id,
            "step_goal": step_goal,
            "route": route,
            "prior_sql": prior_text,
            "retry_feedback": retry_text,
        },
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
    system = _render_prompt_template("synthesis_system", values={})
    user = _render_prompt_template(
        "synthesis_user",
        values={
            "history": _history_text(history),
            "user_message": user_message,
            "route": route,
            "presentation_intent": presentation_intent,
            "result_summary": result_summary,
            "evidence_summary": evidence_summary,
        },
    )
    return system, user
