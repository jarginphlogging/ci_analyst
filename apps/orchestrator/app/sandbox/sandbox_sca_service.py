from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.observability import bind_log_context, configure_logging
from app.providers.anthropic_llm import chat_completion as anthropic_chat_completion
from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite
from app.services.llm_json import as_string_list, parse_json_object
from app.services.llm_schemas import AnalystResponsePayload
from app.services.semantic_model import SemanticModel, load_semantic_model, semantic_model_summary
from app.services.semantic_model_yaml import load_semantic_model_yaml, semantic_model_yaml_prompt_context
from app.services.sql_guardrails import guard_sql

configure_logging()
logger = logging.getLogger(__name__)


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
    retryFeedback: list[dict[str, Any]] = Field(default_factory=list)


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


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip() or str(uuid4())
    started_at = perf_counter()
    with bind_log_context(request_id=request_id):
        logger.info(
            "Sandbox HTTP request started",
            extra={
                "event": "sandbox.http.request.started",
                "method": request.method,
                "path": request.url.path,
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Sandbox HTTP request failed",
                extra={
                    "event": "sandbox.http.request.failed",
                    "method": request.method,
                    "path": request.url.path,
                    "durationMs": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        response.headers["x-request-id"] = request_id
        logger.info(
            "Sandbox HTTP request completed",
            extra={
                "event": "sandbox.http.request.completed",
                "method": request.method,
                "path": request.url.path,
                "statusCode": response.status_code,
                "durationMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return response


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


def _retry_feedback_history(feedback: list[dict[str, Any]]) -> list[str]:
    entries: list[str] = []
    for item in feedback[-3:]:
        phase = str(item.get("phase", "")).strip()
        attempt = str(item.get("attempt", "")).strip()
        error = str(item.get("error", "")).strip()
        failed_sql = str(item.get("failedSql", "")).strip()
        parts = ["Retry context from prior SQL attempt"]
        if phase:
            parts.append(f"phase={phase}")
        if attempt:
            parts.append(f"attempt={attempt}")
        if error:
            parts.append(f"error={error}")
        if failed_sql:
            parts.append(f"failedSql={failed_sql}")
        entries.append("; ".join(parts))
    return entries


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


# Keep sandbox analyst single-attempt so orchestrator-level retry logic remains
# authoritative and trace output is consistent across providers.
_MAX_SQL_ATTEMPTS = 1

_SQL_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["sql_ready", "clarification", "not_relevant"]},
        "sql": {"type": "string"},
        "lightResponse": {"type": "string"},
        "clarificationQuestion": {"type": "string"},
        "notRelevantReason": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "type",
        "sql",
        "lightResponse",
        "clarificationQuestion",
        "notRelevantReason",
        "assumptions",
    ],
}


def _retry_feedback_line(*, error: str, sql: str, attempt: int, max_attempts: int) -> str:
    return (
        f"That didn't work (attempt {attempt}/{max_attempts}). "
        f"Warehouse error (verbatim): {error}\n"
        f"Failed SQL:\n{sql}"
    )


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
        response_schema=_SQL_GENERATION_SCHEMA,
        response_schema_name="sandbox_sql_generation",
    )
    payload = parse_json_object(llm_text)
    parsed = AnalystResponsePayload.model_validate(payload)
    response_type = parsed.type.strip().lower().replace("-", "_")
    if response_type in {"answer", "sql"}:
        response_type = "sql_ready"
    elif response_type == "clarify":
        response_type = "clarification"
    elif response_type in {"out_of_domain", "irrelevant"}:
        response_type = "not_relevant"

    sql = parsed.sql.strip()
    light_response = parsed.lightResponse.strip()
    clarification_question = parsed.clarificationQuestion.strip()
    not_relevant_reason = parsed.notRelevantReason.strip() or parsed.relevanceReason.strip()
    assumptions = as_string_list(parsed.assumptions, max_items=4)

    if response_type == "sql_ready" and not sql:
        response_type = "clarification"
        clarification_question = (
            clarification_question
            or "SQL generation failed: model returned sql_ready without executable SQL."
        )
        assumptions.append("SQL generation failed: model returned sql_ready without executable SQL.")

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
        logger.exception(
            "Sandbox SQL query validation failed",
            extra={
                "event": "sandbox.query.failed_validation",
            },
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        logger.exception(
            "Sandbox SQL query execution failed",
            extra={
                "event": "sandbox.query.failed_execution",
            },
        )
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
    retry_feedback = [item for item in payload.retryFeedback if isinstance(item, dict)]
    retry_feedback_history = _retry_feedback_history(retry_feedback)
    clarification_question = ""
    assumptions: list[str] = []

    guarded_sql = ""
    rows: list[dict[str, Any]] = []
    sql_text = ""
    last_failed_sql = ""
    last_execution_error = ""
    last_retry_message = ""
    had_execution_failure = False
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
        if retry_feedback:
            assumptions.append(f"Used retry feedback from {len(retry_feedback)} prior SQL attempt(s).")
        generation_history = [*conversation_history, *retry_feedback_history]
        for attempt in range(1, _MAX_SQL_ATTEMPTS + 1):
            try:
                generated = await _generate_sql_from_message(user_message, generation_history)
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Sandbox SQL generation attempt failed",
                    extra={
                        "event": "sandbox.message.sql_generation.failed",
                        "attempt": attempt,
                        "conversationId": payload.conversationId,
                    },
                )
                assumptions.append(f"SQL generation attempt {attempt} failed: {error}")
                response_type = "clarification"
                clarification_question = str(error).strip()
                if attempt >= _MAX_SQL_ATTEMPTS:
                    break
                generation_history = [*generation_history, f"SQL generation error: {error}"]
                continue

            response_type = str(generated.get("type", "sql_ready"))
            sql_text = str(generated.get("sql", "")).strip()
            light_response = str(generated.get("lightResponse", "")).strip() or light_response
            clarification_question = str(generated.get("clarificationQuestion", "")).strip()
            not_relevant_reason = str(generated.get("notRelevantReason", "")).strip()
            assumptions.extend(as_string_list(generated.get("assumptions"), max_items=4))

            if response_type != "sql_ready":
                if had_execution_failure and attempt < _MAX_SQL_ATTEMPTS:
                    assumptions.append(
                        "SQL agent requested clarification after execution failure; continuing retry with warehouse error feedback."
                    )
                    if last_retry_message:
                        generation_history = [*generation_history, last_retry_message]
                    continue
                break
            if not sql_text:
                response_type = "clarification"
                clarification_question = clarification_question or not_relevant_reason or "SQL generator returned empty SQL."
                if had_execution_failure and attempt < _MAX_SQL_ATTEMPTS:
                    assumptions.append("SQL generator returned empty SQL after execution failure; continuing retry.")
                    if last_retry_message:
                        generation_history = [*generation_history, last_retry_message]
                    continue
                break

            try:
                guarded_sql, rows = _execute_guarded_sql(sql_text)
                last_failed_sql = ""
                break
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Sandbox SQL execution attempt failed",
                    extra={
                        "event": "sandbox.message.sql_execution.failed",
                        "attempt": attempt,
                        "conversationId": payload.conversationId,
                    },
                )
                assumptions.append(f"SQL execution attempt {attempt} failed: {error}")
                had_execution_failure = True
                last_execution_error = str(error).strip()
                last_failed_sql = sql_text
                last_retry_message = _retry_feedback_line(
                    error=last_execution_error,
                    sql=sql_text,
                    attempt=attempt,
                    max_attempts=_MAX_SQL_ATTEMPTS,
                )
                if attempt >= _MAX_SQL_ATTEMPTS:
                    response_type = "clarification"
                    clarification_question = clarification_question or not_relevant_reason or last_execution_error
                    break
                generation_history = [*generation_history, last_retry_message]

    if response_type == "sql_ready":
        if not guarded_sql:
            if not sql_text:
                raise HTTPException(status_code=400, detail="Sandbox analyst did not return executable SQL.")
            try:
                guarded_sql, rows = _execute_guarded_sql(sql_text)
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Sandbox final SQL execution failed",
                    extra={
                        "event": "sandbox.message.final_sql.failed",
                        "conversationId": payload.conversationId,
                    },
                )
                raise HTTPException(status_code=400, detail=f"{error}") from error

    return {
        "type": "answer" if response_type == "sql_ready" else response_type,
        "conversationId": payload.conversationId,
        "sql": guarded_sql,
        "lightResponse": light_response,
        "clarificationQuestion": clarification_question,
        "notRelevantReason": not_relevant_reason,
        "rows": rows,
        "rowCount": len(rows),
        "failedSql": last_failed_sql,
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
