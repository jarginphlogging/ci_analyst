from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.providers.anthropic_llm import chat_completion as anthropic_chat_completion
from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite
from app.services.llm_json import as_string_list, parse_json_object
from app.services.semantic_model import SemanticModel, load_semantic_model, semantic_model_summary
from app.services.semantic_model_yaml import load_semantic_model_yaml, semantic_model_yaml_prompt_context
from app.services.sql_guardrails import guard_sql


class QueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    sql: str
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = Field(default=None, alias="schema")


class MessageRequest(BaseModel):
    conversationId: str
    message: str
    history: list[str] = Field(default_factory=list)
    route: Optional[str] = None
    stepId: Optional[str] = None


_CONVERSATION_MEMORY: dict[str, list[str]] = {}
_SEMANTIC_MODEL: SemanticModel | None = None
_SEMANTIC_YAML_CONTEXT: str | None = None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    global _SEMANTIC_MODEL, _SEMANTIC_YAML_CONTEXT
    ensure_sandbox_database(settings.sandbox_sqlite_path, reset=settings.sandbox_seed_reset)
    _SEMANTIC_MODEL = load_semantic_model()
    _SEMANTIC_YAML_CONTEXT = semantic_model_yaml_prompt_context(load_semantic_model_yaml())
    yield


app = FastAPI(title="CI Analyst Sandbox Cortex Service", version="0.2.0", lifespan=_lifespan)


def _check_auth(authorization: Optional[str]) -> None:
    # Local sandbox auth is optional by default. If a key is configured, enforce it.
    if not settings.sandbox_cortex_api_key:
        return
    expected = f"Bearer {settings.sandbox_cortex_api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _model() -> SemanticModel:
    if _SEMANTIC_MODEL is None:
        return load_semantic_model()
    return _SEMANTIC_MODEL


def _semantic_yaml_context() -> str:
    if _SEMANTIC_YAML_CONTEXT:
        return _SEMANTIC_YAML_CONTEXT
    return semantic_model_yaml_prompt_context(load_semantic_model_yaml())


def _conversation_history(conversation_id: str, incoming_history: list[str]) -> list[str]:
    stored = _CONVERSATION_MEMORY.get(conversation_id, [])
    merged = [item.strip() for item in [*stored, *incoming_history] if item and item.strip()]
    # Preserve order and remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for item in merged:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[-12:]


def _record_message(conversation_id: str, message: str, history: list[str]) -> list[str]:
    merged = _conversation_history(conversation_id, history)
    merged.append(message.strip())
    _CONVERSATION_MEMORY[conversation_id] = merged[-12:]
    return _CONVERSATION_MEMORY[conversation_id]


def _history_text(history: list[str]) -> str:
    recent = history[-8:]
    return "\n".join(f"- {item}" for item in recent) or "- none"


def _needs_clarification(message: str) -> bool:
    lowered = message.lower().strip()
    if len(lowered.split()) <= 3:
        return True
    vague_markers = [
        "what happened",
        "show me everything",
        "give me insight",
        "analyze this",
        "help me understand",
        "details please",
    ]
    specific_markers = [
        "state",
        "store",
        "channel",
        "spend",
        "transaction",
        "q4",
        "month",
        "year",
        "repeat",
        "new",
        "cp",
        "cnp",
    ]
    if any(marker in lowered for marker in specific_markers):
        return False
    return any(marker in lowered for marker in vague_markers)


_MAX_SQL_ATTEMPTS = 2


async def _generate_sql_from_message(message: str, conversation_history: list[str]) -> dict[str, Any]:
    model = _model()
    system_prompt = (
        "You are a sandbox Snowflake Cortex Analyst emulator for banking analytics. "
        "For each request, return exactly one outcome: sql_ready, clarification, or not_relevant. "
        "Use semantic_model.yaml context to determine scope. "
        "When sql_ready, generate one Snowflake-style read-only SQL query from conversation context. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"{_semantic_yaml_context()}\n\n"
        f"{semantic_model_summary(model)}\n\n"
        f"Conversation history:\n{_history_text(conversation_history)}\n\n"
        f"User question:\n{message}\n\n"
        "Return JSON with keys:\n"
        '- "type": one of sql_ready|clarification|not_relevant\n'
        '- "sql": string (required when type=sql_ready)\n'
        '- "lightResponse": short one-sentence summary\n'
        '- "clarificationQuestion": string (required when type=clarification)\n'
        '- "notRelevantReason": string (required when type=not_relevant)\n'
        '- "assumptions": array of strings\n'
    )

    llm_text = await anthropic_chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=800,
        response_json=True,
    )
    payload = parse_json_object(llm_text)
    response_type = str(payload.get("type", "sql_ready")).strip().lower().replace("-", "_")
    if response_type not in {"sql_ready", "clarification", "not_relevant"}:
        response_type = "sql_ready"

    sql = str(payload.get("sql", "")).strip()
    light_response = str(payload.get("lightResponse", "")).strip()
    clarification_question = str(payload.get("clarificationQuestion", "")).strip()
    not_relevant_reason = str(payload.get("notRelevantReason", "")).strip()
    assumptions = as_string_list(payload.get("assumptions"), max_items=4)

    if response_type == "sql_ready" and not sql:
        response_type = "clarification"
        clarification_question = (
            clarification_question
            or "Could you clarify the metric, grain, and time window so I can generate the right SQL?"
        )

    return {
        "type": response_type,
        "sql": sql,
        "lightResponse": light_response,
        "clarificationQuestion": clarification_question,
        "notRelevantReason": not_relevant_reason,
        "assumptions": assumptions,
    }


def _execute_guarded_sql(sql: str) -> tuple[str, list[dict[str, Any]]]:
    guarded_sql = guard_sql(sql, _model())
    rows = execute_readonly_query(settings.sandbox_sqlite_path, guarded_sql)
    return guarded_sql, rows


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "database": settings.sandbox_sqlite_path,
        "conversationCount": len(_CONVERSATION_MEMORY),
    }


@app.post("/api/v2/cortex/analyst/query")
@app.post("/query")
async def query(payload: QueryRequest, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    try:
        rows = execute_readonly_query(settings.sandbox_sqlite_path, payload.sql)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Sandbox SQL execution failed: {error}") from error

    return {
        "rows": rows,
        "rowCount": len(rows),
        "rewrittenSql": rewrite_sql_for_sqlite(payload.sql),
    }


@app.post("/api/v2/cortex/analyst/message")
@app.post("/message")
async def message(payload: MessageRequest, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is required")

    conversation_history = _record_message(payload.conversationId, user_message, payload.history)
    clarification_question = ""
    assumptions: list[str] = []

    guarded_sql = ""
    rows: list[dict[str, Any]] = []
    sql_text = ""
    light_response = "Returned a governed summary for the requested customer-insights metric."
    response_type = "sql_ready"
    not_relevant_reason = ""

    if _needs_clarification(user_message):
        response_type = "clarification"
        clarification_question = (
            "Could you clarify the metric and time window? For example: spend vs transactions, and which month/quarter."
        )
        assumptions.append("Question was interpreted as broad; clarification is required before SQL generation.")
    else:
        generation_history = list(conversation_history)
        for attempt in range(1, _MAX_SQL_ATTEMPTS + 1):
            try:
                generated = await _generate_sql_from_message(user_message, generation_history)
            except Exception as error:  # noqa: BLE001
                assumptions.append(f"SQL generation attempt {attempt} failed: {error}")
                if attempt >= _MAX_SQL_ATTEMPTS:
                    response_type = "clarification"
                    clarification_question = (
                        "I couldn't generate valid SQL for that task. Please restate the metric, grain, and time window."
                    )
                    break
                generation_history = [*conversation_history, f"Previous generation error: {error}"]
                continue

            response_type = str(generated.get("type", "sql_ready"))
            sql_text = str(generated.get("sql", "")).strip()
            light_response = str(generated.get("lightResponse", "")).strip() or light_response
            clarification_question = str(generated.get("clarificationQuestion", "")).strip()
            not_relevant_reason = str(generated.get("notRelevantReason", "")).strip()
            assumptions.extend(as_string_list(generated.get("assumptions"), max_items=4))

            if response_type != "sql_ready":
                break
            if not sql_text:
                response_type = "clarification"
                clarification_question = (
                    clarification_question
                    or "I need a clearer metric, grain, and time window before generating SQL."
                )
                break

            try:
                guarded_sql, rows = _execute_guarded_sql(sql_text)
                break
            except Exception as error:  # noqa: BLE001
                assumptions.append(f"SQL execution attempt {attempt} failed: {error}")
                if attempt >= _MAX_SQL_ATTEMPTS:
                    response_type = "clarification"
                    clarification_question = (
                        "I couldn't execute a valid query for that task. Please restate the metric, grain, and time window."
                    )
                    sql_text = ""
                    break
                generation_history = [
                    *conversation_history,
                    f"Previous SQL failed to execute: {error}",
                    f"Previous SQL:\n{sql_text}",
                ]

    if response_type == "sql_ready":
        if not guarded_sql:
            if not sql_text:
                raise HTTPException(status_code=400, detail="Sandbox analyst did not return executable SQL.")
            try:
                guarded_sql, rows = _execute_guarded_sql(sql_text)
            except Exception as error:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"Sandbox analyst execution failed: {error}") from error

    return {
        "type": "answer" if response_type == "sql_ready" else response_type,
        "conversationId": payload.conversationId,
        "sql": guarded_sql,
        "lightResponse": light_response,
        "clarificationQuestion": clarification_question,
        "notRelevantReason": not_relevant_reason,
        "rows": rows,
        "rowCount": len(rows),
        "assumptions": assumptions[:6],
    }


@app.get("/api/v2/cortex/analyst/history/{conversation_id}")
async def history(conversation_id: str, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    return {
        "conversationId": conversation_id,
        "history": _CONVERSATION_MEMORY.get(conversation_id, []),
    }


if __name__ == "__main__":
    uvicorn.run("app.sandbox.sandbox_sca_service:app", host="0.0.0.0", port=8788, reload=False)
