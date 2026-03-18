from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.orchestrator import ConversationalOrchestrator
from tests.orchestrator_test_support import DeterministicDependencies


@pytest.mark.asyncio
async def test_run_turn_returns_payload() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="What changed in charge-off risk this quarter?")
    )

    assert result.turnId
    assert len(result.response.summary.answer) > 20
    assert result.response.data.dataTables
    assert len(result.response.trace) == 5
    assert result.response.trace[0].stageInput is not None
    assert result.response.trace[0].stageOutput is not None
    assert result.response.trace[2].stageOutput is not None
    assert result.response.trace[2].qualityChecks
