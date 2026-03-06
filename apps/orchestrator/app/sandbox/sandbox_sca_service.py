from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.observability import bind_log_context, configure_logging
from app.providers.anthropic_llm import chat_completion as anthropic_chat_completion
from app.prompts.templates import sql_prompt
from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite
from app.services.llm_json import as_string_list, parse_json_object
from app.services.llm_schemas import SqlGenerationResponsePayload
from app.services.semantic_model import SemanticModel, load_semantic_model

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
    stepId: Optional[str] = None
    retryFeedback: list[dict[str, Any]] = Field(default_factory=list)
    dependencyContext: list[dict[str, Any]] = Field(default_factory=list)


_CONVERSATION_MEMORY: dict[str, list[str]] = {}
_SEMANTIC_MODEL: SemanticModel | None = None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    global _SEMANTIC_MODEL
    ensure_sandbox_database(settings.sandbox_sqlite_path, reset=settings.sandbox_seed_reset)
    _SEMANTIC_MODEL = load_semantic_model()
    yield


app = FastAPI(title="CI Analyst Sandbox Cortex Service", version="0.2.0", lifespan=_lifespan)

_MESSAGE_SQL_GENERATION_MAX_ATTEMPTS = 2
_MESSAGE_SQL_GENERATION_RETRY_DELAY_SECONDS = 0.25


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


def _clean_assumptions(assumptions: list[str], *, clarification_question: str) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    question_key = " ".join(str(clarification_question or "").split()).strip().lower()
    for item in assumptions:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        key = text.lower()
        if question_key and key == question_key:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped[:6]


_SQL_GENERATION_SCHEMA: dict[str, Any] = SqlGenerationResponsePayload.model_json_schema()


class SandboxSqlGenerationError(RuntimeError):
    def __init__(self, message: str, *, code: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


def _preview_text(value: Any, *, max_chars: int = 1200) -> str:
    collapsed = " ".join(str(value or "").split()).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 3]}..."


def _preview_payload(value: Any, *, max_chars: int = 2000) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=True)
    except Exception:  # noqa: BLE001
        rendered = str(value)
    if len(rendered) <= max_chars:
        return rendered
    return f"{rendered[: max_chars - 3]}..."


def _to_analyst_payload(*, parsed: SqlGenerationResponsePayload) -> dict[str, Any]:
    response_type = parsed.generationType.strip().lower().replace("-", "_")
    sql = (parsed.sql or "").strip()
    light_response = parsed.rationale.strip()
    clarification_question = (parsed.clarificationQuestion or "").strip()
    clarification_kind = (parsed.clarificationKind or "").strip().lower().replace("-", "_")
    not_relevant_reason = (parsed.notRelevantReason or "").strip()
    assumptions = as_string_list(parsed.assumptions, max_items=4)

    assumptions = _clean_assumptions(assumptions, clarification_question=clarification_question)
    return {
        "type": response_type,
        "sql": sql,
        "lightResponse": light_response,
        "clarificationQuestion": clarification_question,
        "clarificationKind": clarification_kind,
        "notRelevantReason": not_relevant_reason,
        "assumptions": assumptions,
    }


async def _generate_sql_from_message(
    *,
    message: str,
    step_id: str,
    conversation_history: list[str],
    retry_feedback: list[dict[str, Any]],
    dependency_context: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    system_prompt, user_prompt = sql_prompt(
        user_message=message,
        step_id=step_id,
        step_goal=message,
        model=_model(),
        prior_sql=[],
        history=conversation_history,
        retry_feedback=retry_feedback,
        dependency_context=dependency_context,
    )

    llm_text = await anthropic_chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=800,
        response_schema=_SQL_GENERATION_SCHEMA,
        response_schema_name="sandbox_sql_generation",
    )
    try:
        raw_payload = parse_json_object(llm_text)
    except Exception as error:  # noqa: BLE001
        raise SandboxSqlGenerationError(
            "Sandbox SQL generation output was not valid JSON.",
            code="json_parse_error",
            detail={
                "errorType": type(error).__name__,
                "parseError": _preview_text(str(error), max_chars=800),
                "llmTextPreview": _preview_text(llm_text, max_chars=1400),
            },
        ) from error
    try:
        parsed = SqlGenerationResponsePayload.model_validate(raw_payload)
    except Exception as error:  # noqa: BLE001
        raise SandboxSqlGenerationError(
            "Sandbox SQL generation payload failed schema validation.",
            code="schema_validation_error",
            detail={
                "errorType": type(error).__name__,
                "validationError": _preview_text(str(error), max_chars=1400),
                "rawPayloadPreview": _preview_payload(raw_payload, max_chars=2200),
                "llmTextPreview": _preview_text(llm_text, max_chars=1400),
            },
        ) from error
    return _to_analyst_payload(parsed=parsed)


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
        rows = await run_in_threadpool(
            execute_readonly_query,
            settings.sandbox_sqlite_path,
            payload.sql,
        )
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
    generation_history = list(conversation_history)
    generated: dict[str, Any] | None = None
    last_sandbox_error: SandboxSqlGenerationError | None = None
    last_generic_error: Exception | None = None
    for attempt in range(1, _MESSAGE_SQL_GENERATION_MAX_ATTEMPTS + 1):
        try:
            generated = await _generate_sql_from_message(
                message=user_message,
                step_id=(payload.stepId or "").strip(),
                conversation_history=generation_history,
                retry_feedback=retry_feedback,
                dependency_context=payload.dependencyContext,
            )
            break
        except SandboxSqlGenerationError as error:
            last_sandbox_error = error
            is_retryable = error.code in {"json_parse_error", "schema_validation_error"}
            if is_retryable and attempt < _MESSAGE_SQL_GENERATION_MAX_ATTEMPTS:
                logger.warning(
                    "Sandbox SQL generation returned malformed payload; retrying",
                    extra={
                        "event": "sandbox.message.sql_generation.retry",
                        "conversationId": payload.conversationId,
                        "attempt": attempt,
                        "maxAttempts": _MESSAGE_SQL_GENERATION_MAX_ATTEMPTS,
                        "errorCode": error.code,
                    },
                )
                await asyncio.sleep(_MESSAGE_SQL_GENERATION_RETRY_DELAY_SECONDS * attempt)
                continue
            break
        except Exception as error:  # noqa: BLE001
            last_generic_error = error
            if attempt < _MESSAGE_SQL_GENERATION_MAX_ATTEMPTS:
                logger.warning(
                    "Sandbox SQL generation provider error; retrying",
                    extra={
                        "event": "sandbox.message.sql_generation.retry_provider",
                        "conversationId": payload.conversationId,
                        "attempt": attempt,
                        "maxAttempts": _MESSAGE_SQL_GENERATION_MAX_ATTEMPTS,
                        "errorType": type(error).__name__,
                    },
                )
                await asyncio.sleep(_MESSAGE_SQL_GENERATION_RETRY_DELAY_SECONDS * attempt)
                continue
            break

    if generated is None:
        if last_sandbox_error is not None:
            logger.exception(
                "Sandbox SQL generation failed",
                extra={
                    "event": "sandbox.message.sql_generation.failed",
                    "conversationId": payload.conversationId,
                    "errorCode": last_sandbox_error.code,
                },
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": last_sandbox_error.code,
                    "message": str(last_sandbox_error),
                    **last_sandbox_error.detail,
                },
            ) from last_sandbox_error
        if last_generic_error is not None:
            logger.exception(
                "Sandbox SQL generation failed",
                extra={
                    "event": "sandbox.message.sql_generation.failed",
                    "conversationId": payload.conversationId,
                },
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "provider_error",
                    "message": "SQL generation provider error.",
                    "errorType": type(last_generic_error).__name__,
                    "error": _preview_text(str(last_generic_error), max_chars=1200),
                },
            ) from last_generic_error
        raise HTTPException(status_code=502, detail={"code": "provider_error", "message": "SQL generation failed."})

    response_type = str(generated.get("type", "sql_ready")).strip().lower()
    sql_text = str(generated.get("sql", "")).strip()
    light_response = str(generated.get("lightResponse", "")).strip()
    clarification_question = str(generated.get("clarificationQuestion", "")).strip()
    clarification_kind = str(generated.get("clarificationKind", "")).strip()
    not_relevant_reason = str(generated.get("notRelevantReason", "")).strip()
    assumptions = _clean_assumptions(
        as_string_list(generated.get("assumptions"), max_items=4),
        clarification_question=clarification_question,
    )
    if response_type == "sql_ready" and not sql_text:
        raise HTTPException(status_code=502, detail="SQL generation provider error: empty SQL.")

    return {
        "type": response_type,
        "conversationId": payload.conversationId,
        "sql": sql_text if response_type == "sql_ready" else "",
        "lightResponse": light_response,
        "clarificationQuestion": clarification_question,
        "clarificationKind": clarification_kind,
        "notRelevantReason": not_relevant_reason,
        "rows": [],
        "rowCount": 0,
        "failedSql": None,
        "assumptions": assumptions,
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
