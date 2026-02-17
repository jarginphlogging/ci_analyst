from __future__ import annotations

import asyncio
import json

import uvicorn
from fastapi import FastAPI, HTTPException
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
from app.services.dependencies import create_dependencies
from app.services.orchestrator import ConversationalOrchestrator

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


@app.get("/health")
async def health() -> dict[str, str]:
    from app.models import now_iso

    return {"status": "ok", "timestamp": now_iso(), "providerMode": settings.provider_mode}


@app.post("/v1/chat/turn", responses={400: {"model": ErrorResponse}})
async def chat_turn(request: ChatTurnRequest):
    try:
        result = await orchestrator.run_turn(request)
        return JSONResponse(content=result.model_dump())
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatTurnRequest):
    async def event_stream():
        try:
            stream_result = await orchestrator.run_stream(request)

            for event in stream_result.events:
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
            yield f"{ErrorEvent(type='error', message=str(error)).model_dump_json()}\n"
            yield f"{DoneEvent(type='done').model_dump_json()}\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson; charset=utf-8")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)
