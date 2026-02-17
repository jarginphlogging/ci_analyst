from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.dependencies import create_dependencies
from app.services.orchestrator import ConversationalOrchestrator


@pytest.mark.asyncio
async def test_run_turn_returns_payload() -> None:
    orchestrator = ConversationalOrchestrator(create_dependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="What changed in charge-off risk this quarter?")
    )

    assert result.turnId
    assert len(result.response.answer) > 20
    assert result.response.dataTables


@pytest.mark.asyncio
async def test_run_stream_returns_done_event() -> None:
    orchestrator = ConversationalOrchestrator(create_dependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="Where are fraud losses accelerating?")
    )

    assert stream_result.events[-1]["type"] == "done"
    assert any(event["type"] == "answer_delta" for event in stream_result.events)
    assert any(event["type"] == "response" for event in stream_result.events)
