from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.orchestrator import ConversationalOrchestrator
from tests.orchestrator_test_support import DeterministicDependencies


@pytest.mark.asyncio
async def test_run_stream_returns_done_event() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="Where are fraud losses accelerating?")
    )

    assert stream_result.events[-1]["type"] == "done"
    assert any(event["type"] == "answer_delta" for event in stream_result.events)
    assert any(event["type"] == "response" for event in stream_result.events)


@pytest.mark.asyncio
async def test_stream_status_messages_avoid_sql_wording() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="Summarize recent channel performance.")
    )

    status_messages = [
        str(event.get("message", "")).lower()
        for event in stream_result.events
        if event.get("type") == "status"
    ]
    assert status_messages
    assert all("sql" not in message for message in status_messages)
