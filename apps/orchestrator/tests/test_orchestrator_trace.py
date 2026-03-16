from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.llm_trace import LlmTraceEntry
from app.services.orchestrator import ConversationalOrchestrator
from tests.orchestrator_test_support import (
    DeterministicDependencies,
    GenerationRetryFeedbackDependencies,
    RetryFeedbackDependencies,
)


@pytest.mark.asyncio
async def test_trace_exposes_retry_feedback_and_warehouse_errors() -> None:
    orchestrator = ConversationalOrchestrator(RetryFeedbackDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="What changed in charge-off risk this quarter?")
    )

    sql_trace = result.response.trace[1]
    assert sql_trace.id == "t2"
    assert sql_trace.stageOutput is not None
    retry_feedback = sql_trace.stageOutput.get("retryFeedback")
    warehouse_errors = sql_trace.stageOutput.get("warehouseErrors")
    assert isinstance(retry_feedback, list)
    assert isinstance(warehouse_errors, list)
    assert retry_feedback
    assert warehouse_errors
    assert "invalid identifier BOGUS_COL" in str(warehouse_errors[0].get("error", ""))


@pytest.mark.asyncio
async def test_trace_excludes_generation_errors_from_warehouse_errors() -> None:
    orchestrator = ConversationalOrchestrator(GenerationRetryFeedbackDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="Why did sales change month over month?")
    )

    sql_trace = result.response.trace[1]
    assert sql_trace.id == "t2"
    assert sql_trace.stageOutput is not None
    warehouse_errors = sql_trace.stageOutput.get("warehouseErrors")
    assert isinstance(warehouse_errors, list)
    assert warehouse_errors == []


def test_llm_response_payload_includes_human_readable_trace_response() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    payload = orchestrator._llm_response_payload(  # noqa: SLF001
        [
            LlmTraceEntry(
                stage="plan_generation",
                provider="anthropic",
                system_prompt="system",
                user_prompt="user",
                max_tokens=100,
                temperature=0.1,
                raw_response='{"relevance":"in_domain","relevanceReason":"Maps to governed sales metrics."}',
                parsed_response={
                    "relevance": "in_domain",
                    "relevanceReason": "Maps to governed sales metrics.",
                },
            )
        ]
    )

    assert payload[0]["humanResponse"] == "Maps to governed sales metrics."
