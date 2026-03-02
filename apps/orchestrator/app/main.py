from __future__ import annotations

import asyncio
import json
import logging
from time import perf_counter
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.models import (
    AnswerDeltaEvent,
    ChatTurnRequest,
    DoneEvent,
    ErrorEvent,
    ErrorResponse,
    ResponseEvent,
    StatusEvent,
)
from app.observability import bind_log_context, configure_logging, get_request_id
from app.services.dependencies import create_dependencies
from app.services.orchestrator import ConversationalOrchestrator

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="CI Analyst Orchestrator", version="0.1.0")
orchestrator = ConversationalOrchestrator(create_dependencies())


def _event_delay_seconds(event_type: str) -> float:
    if settings.provider_mode != "mock":
        return 0.0
    if event_type == "status":
        return max(settings.mock_stream_status_delay_ms, 0) / 1000
    if event_type == "answer_delta":
        return max(settings.mock_stream_token_delay_ms, 0) / 1000
    if event_type == "response":
        return max(settings.mock_stream_response_delay_ms, 0) / 1000
    return 0.0


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip() or str(uuid4())
    started_at = perf_counter()
    client_host = request.client.host if request.client else None

    with bind_log_context(request_id=request_id):
        logger.info(
            "HTTP request started",
            extra={
                "event": "http.request.started",
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "clientIp": client_host,
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "HTTP request failed",
                extra={
                    "event": "http.request.failed",
                    "method": request.method,
                    "path": request.url.path,
                    "durationMs": elapsed_ms,
                },
            )
            raise

        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        response.headers["x-request-id"] = request_id
        logger.info(
            "HTTP request completed",
            extra={
                "event": "http.request.completed",
                "method": request.method,
                "path": request.url.path,
                "statusCode": response.status_code,
                "durationMs": elapsed_ms,
            },
        )
        return response


@app.get("/health")
async def health() -> dict[str, str]:
    from app.models import now_iso

    return {"status": "ok", "timestamp": now_iso(), "providerMode": settings.provider_mode}


@app.post("/v1/chat/turn", responses={400: {"model": ErrorResponse}})
async def chat_turn(request: ChatTurnRequest):
    session_id = str(request.sessionId or "anonymous")
    with bind_log_context(session_id=session_id):
        logger.info(
            "Chat turn received",
            extra={
                "event": "chat.turn.received",
                "sessionIdValue": session_id,
                "messageChars": len(request.message),
            },
        )
        try:
            result = await orchestrator.run_turn(request)
            logger.info(
                "Chat turn completed",
                extra={
                    "event": "chat.turn.completed",
                    "sessionIdValue": session_id,
                    "traceSteps": len(result.response.trace),
                    "insightCount": len(result.response.insights),
                },
            )
            return JSONResponse(content=result.model_dump())
        except Exception as error:  # noqa: BLE001
            logger.exception(
                "Chat turn failed",
                extra={
                    "event": "chat.turn.failed",
                    "sessionIdValue": session_id,
                    "messagePreview": " ".join(request.message.split())[:180],
                },
            )
            raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatTurnRequest):
    session_id = str(request.sessionId or "anonymous")
    request_id = get_request_id()

    async def event_stream():
        emitted_events = 0
        with bind_log_context(request_id=request_id, session_id=session_id):
            logger.info(
                "Chat stream started",
                extra={
                    "event": "chat.stream.started",
                    "sessionIdValue": session_id,
                    "messageChars": len(request.message),
                },
            )
            try:
                async for event in orchestrator.stream_events(request):
                    emitted_events += 1
                    event_type = event.get("type")
                    if event_type == "status":
                        StatusEvent(**event)
                    elif event_type == "answer_delta":
                        AnswerDeltaEvent(**event)
                    elif event_type == "response":
                        ResponseEvent(**event)
                    elif event_type == "done":
                        DoneEvent(**event)

                    yield f"{json.dumps(event)}\n"
                    delay_seconds = _event_delay_seconds(event_type or "")
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Chat stream failed",
                    extra={
                        "event": "chat.stream.failed",
                        "sessionIdValue": session_id,
                        "eventsEmitted": emitted_events,
                    },
                )
                yield f"{ErrorEvent(type='error', message=str(error)).model_dump_json()}\n"
                yield f"{DoneEvent(type='done').model_dump_json()}\n"
            finally:
                logger.info(
                    "Chat stream finished",
                    extra={
                        "event": "chat.stream.finished",
                        "sessionIdValue": session_id,
                        "eventsEmitted": emitted_events,
                    },
                )

    return StreamingResponse(event_stream(), media_type="application/x-ndjson; charset=utf-8")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)
