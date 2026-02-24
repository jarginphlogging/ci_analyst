from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest, QueryPlanStep
from app.services.orchestrator import ConversationalOrchestrator
from app.services.stages import PlannerBlockedError, SqlGenerationBlockedError
from app.services.types import TurnExecutionContext

GENERIC_FAILURE = "I couldn't complete that request. Please review the trace for details."


class OutOfDomainDependencies:
    async def create_plan(self, request: ChatTurnRequest, history: list[str]):  # noqa: ARG002
        raise PlannerBlockedError(
            stop_reason="out_of_domain",
            user_message="I can only answer questions about Customer Insights.",
        )

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ):
        raise AssertionError("run_sql should not be called when planner blocks the request")

    async def validate_results(self, results):  # noqa: ARG002
        raise AssertionError("validate_results should not be called when planner blocks the request")

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_response should not be called when planner blocks the request")

    async def build_fast_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_fast_response should not be called when planner blocks the request")


class ClarificationDependencies:
    async def create_plan(self, request: ChatTurnRequest, history: list[str]):  # noqa: ARG002
        return TurnExecutionContext(route="standard", plan=[])

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ):
        raise SqlGenerationBlockedError(
            stop_reason="clarification",
            user_message="Which metric and time window should I use?",
        )

    async def validate_results(self, results):  # noqa: ARG002
        raise AssertionError("validate_results should not be called when SQL generation blocks")

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_response should not be called when SQL generation blocks")

    async def build_fast_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_fast_response should not be called when SQL generation blocks")


class SqlRuntimeFailureDependencies:
    async def create_plan(self, request: ChatTurnRequest, history: list[str]):  # noqa: ARG002
        return TurnExecutionContext(
            route="standard",
            plan=[QueryPlanStep(id="step_1", goal="Calculate total sales for last month")],
        )

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ):
        raise RuntimeError("no such function: DATE_TRUNC")

    async def validate_results(self, results):  # noqa: ARG002
        raise AssertionError("validate_results should not be called when SQL execution fails")

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_response should not be called when SQL execution fails")

    async def build_fast_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_fast_response should not be called when SQL execution fails")


class UnexpectedFailureDependencies:
    async def create_plan(self, request: ChatTurnRequest, history: list[str]):  # noqa: ARG002
        raise RuntimeError("planner crash")

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ):
        raise AssertionError("run_sql should not be called when planner crashes")

    async def validate_results(self, results):  # noqa: ARG002
        raise AssertionError("validate_results should not be called when planner crashes")

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_response should not be called when planner crashes")

    async def build_fast_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results,
        history: list[str],
    ):
        raise AssertionError("build_fast_response should not be called when planner crashes")


@pytest.mark.asyncio
async def test_run_turn_returns_guardrail_response_when_out_of_domain() -> None:
    orchestrator = ConversationalOrchestrator(OutOfDomainDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="What is the weather today?")
    )

    assert result.response.answer == GENERIC_FAILURE
    assert result.response.trace[0].status == "blocked"
    assert result.response.trace[0].stageOutput is not None
    assert result.response.dataTables == []
    assert result.response.insights == []
    assert result.response.suggestedQuestions == []
    assert result.response.assumptions == []


@pytest.mark.asyncio
async def test_run_stream_returns_guardrail_response_when_out_of_domain() -> None:
    orchestrator = ConversationalOrchestrator(OutOfDomainDependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="What is the weather today?")
    )

    assert stream_result.events[-1]["type"] == "done"
    response_events = [event for event in stream_result.events if event.get("type") == "response"]
    assert response_events
    assert response_events[-1]["response"]["answer"] == GENERIC_FAILURE


@pytest.mark.asyncio
async def test_run_turn_returns_clarification_when_sql_generation_blocks() -> None:
    orchestrator = ConversationalOrchestrator(ClarificationDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="Show me details")
    )

    assert result.response.answer == GENERIC_FAILURE
    assert result.response.trace[0].status == "blocked"
    assert result.response.trace[0].stageOutput is not None
    assert result.response.dataTables == []
    assert result.response.insights == []
    assert result.response.suggestedQuestions == []
    assert result.response.assumptions == []


@pytest.mark.asyncio
async def test_run_turn_returns_trace_when_sql_runtime_fails_unexpectedly() -> None:
    orchestrator = ConversationalOrchestrator(SqlRuntimeFailureDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="what were my total sales for last month")
    )

    assert result.response.answer == GENERIC_FAILURE
    assert result.response.trace[0].id == "t2"
    assert result.response.trace[0].status == "blocked"
    assert result.response.trace[0].stageOutput is not None
    failure = result.response.trace[0].stageOutput.get("failureDetail", {})
    assert "DATE_TRUNC" in str(failure.get("error", ""))


@pytest.mark.asyncio
async def test_run_turn_returns_failure_trace_when_unexpected_error_occurs() -> None:
    orchestrator = ConversationalOrchestrator(UnexpectedFailureDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="what were my total sales for last month")
    )

    assert result.response.answer == GENERIC_FAILURE
    assert result.response.trace[0].id == "t0"
    assert result.response.trace[0].status == "blocked"
    assert result.response.trace[0].stageOutput is not None
    assert "planner crash" in str(result.response.trace[0].stageOutput.get("error", ""))


@pytest.mark.asyncio
async def test_run_stream_returns_failure_trace_when_unexpected_error_occurs() -> None:
    orchestrator = ConversationalOrchestrator(UnexpectedFailureDependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="what were my total sales for last month")
    )

    response_events = [event for event in stream_result.events if event.get("type") == "response"]
    assert response_events
    response_payload = response_events[-1]["response"]
    assert response_payload["answer"] == GENERIC_FAILURE
    assert response_payload["trace"][0]["id"] == "t0"
    assert response_payload["trace"][0]["status"] == "blocked"
    assert "planner crash" in str(response_payload["trace"][0]["stageOutput"]["error"])
