from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import (
    AgentResponse,
    ChatTurnRequest,
    DataTable,
    Insight,
    MetricPoint,
    QueryPlanStep,
    SqlExecutionResult,
    TraceStep,
    ValidationResult,
)
from app.services.orchestrator import ConversationalOrchestrator
from app.services.types import TurnExecutionContext


class DeterministicDependencies:
    async def create_plan(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> TurnExecutionContext:
        return TurnExecutionContext(
            route="fast_path",
            plan=[QueryPlanStep(id="step_1", goal="Retrieve KPI summary by state.")],
        )

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ) -> list[SqlExecutionResult]:
        _ = context
        return [
            SqlExecutionResult(
                sql=(
                    "SELECT transaction_state, current_value, prior_value, change_value "
                    "FROM cia_sales_insights_cortex"
                ),
                rows=[
                    {
                        "transaction_state": "TX",
                        "current_value": 120.0,
                        "prior_value": 100.0,
                        "change_value": 20.0,
                    }
                ],
                rowCount=1,
            )
        ]

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:  # noqa: ARG002
        return ValidationResult(passed=True, checks=["validation_ok"])

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        _ = context
        _ = results
        _ = history
        return AgentResponse(
            answer="Final narrative answer with concrete recommendation details.",
            confidence="high",
            whyItMatters="This helps prioritize state-level interventions.",
            metrics=[MetricPoint(label="Rows Retrieved", value=1, delta=0, unit="count")],
            evidence=[],
            insights=[Insight(id="i1", title="Top state", detail="TX leads.", importance="high")],
            suggestedQuestions=["Which channels drove TX?"],
            assumptions=["A1"],
            trace=[TraceStep(id="t3", title="Synthesis", summary="done", status="done")],
            dataTables=[
                DataTable(
                    id="table_1",
                    name="state_summary",
                    columns=["transaction_state", "current_value", "prior_value", "change_value"],
                    rows=[{"transaction_state": "TX", "current_value": 120.0, "prior_value": 100.0, "change_value": 20.0}],
                    rowCount=1,
                )
            ],
            artifacts=[],
        )

    async def build_fast_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        response = await self.build_response(request, context, results, history)
        return response.model_copy(update={"answer": "Draft answer"})


@pytest.mark.asyncio
async def test_run_turn_returns_payload() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    result = await orchestrator.run_turn(
        ChatTurnRequest(sessionId=uuid4(), message="What changed in charge-off risk this quarter?")
    )

    assert result.turnId
    assert len(result.response.answer) > 20
    assert result.response.dataTables
    assert len(result.response.trace) == 4
    assert result.response.trace[0].stageInput is not None
    assert result.response.trace[0].stageOutput is not None
    assert result.response.trace[2].stageOutput is not None
    assert result.response.trace[2].qualityChecks


@pytest.mark.asyncio
async def test_run_stream_returns_done_event() -> None:
    orchestrator = ConversationalOrchestrator(DeterministicDependencies())
    stream_result = await orchestrator.run_stream(
        ChatTurnRequest(sessionId=uuid4(), message="Where are fraud losses accelerating?")
    )

    assert stream_result.events[-1]["type"] == "done"
    assert any(event["type"] == "answer_delta" for event in stream_result.events)
    assert any(event["type"] == "response" for event in stream_result.events)
