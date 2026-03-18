from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import (
    AgentResponse,
    ChatTurnRequest,
    DataTable,
    Insight,
    QueryPlanStep,
    ResponseAudit,
    ResponseData,
    ResponseSummary,
    ResponseVisualization,
    SqlExecutionResult,
    TraceStep,
    ValidationResult,
)
from app.services.orchestrator import ConversationalOrchestrator
from app.services.types import TurnExecutionContext


class HistorySpyDependencies:
    def __init__(self) -> None:
        self.plan_histories: list[list[str]] = []
        self.sql_histories: list[list[str]] = []
        self.response_histories: list[list[str]] = []

    async def create_plan(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> TurnExecutionContext:
        self.plan_histories.append(list(history))
        return TurnExecutionContext(
            plan=[QueryPlanStep(id="step_1", goal="Retrieve primary KPI")],
        )

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback=None,
    ) -> list[SqlExecutionResult]:
        _ = context
        self.sql_histories.append(list(history))
        return [
            SqlExecutionResult(
                sql="SELECT 'segment' AS segment, 1.0 AS prior, 2.0 AS current, 100.0 AS changeBps, 0.8 AS contribution",
                rows=[
                    {
                        "segment": "segment",
                        "prior": 1.0,
                        "current": 2.0,
                        "changeBps": 100.0,
                        "contribution": 0.8,
                    }
                ],
                rowCount=1,
            )
        ]

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:  # noqa: ARG002
        return ValidationResult(passed=True, checks=["ok"])

    async def build_response(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        _ = context
        self.response_histories.append(list(history))
        return AgentResponse(
            summary=ResponseSummary(
                answer="Answer",
                confidence="high",
                whyItMatters="Why",
                summaryCards=[],
                insights=[Insight(id="i1", title="Insight", detail="Detail", importance="high")],
                suggestedQuestions=["Q1", "Q2", "Q3"],
                assumptions=["A1"],
            ),
            visualization=ResponseVisualization(),
            data=ResponseData(
                dataTables=[
                    DataTable(
                        id="table_1",
                        name="result_1",
                        columns=["segment", "prior", "current", "changeBps", "contribution"],
                        rows=[],
                        rowCount=0,
                    )
                ],
                evidence=[],
            ),
            audit=ResponseAudit(),
            trace=[
                TraceStep(
                    id="t3",
                    title="Synthesize",
                    summary="done",
                    status="done",
                )
            ],
        )

@pytest.mark.asyncio
async def test_orchestrator_carries_prior_history_only() -> None:
    dependencies = HistorySpyDependencies()
    orchestrator = ConversationalOrchestrator(dependencies)
    session_id = uuid4()

    first = ChatTurnRequest(sessionId=session_id, message="Show sales by state")
    second = ChatTurnRequest(sessionId=session_id, message="Now split by card-present channel")

    await orchestrator.run_turn(first)
    second_turn = await orchestrator.run_turn(second)

    assert dependencies.plan_histories[0] == []
    assert dependencies.sql_histories[0] == []
    assert dependencies.response_histories[0] == []

    expected_history = ["Show sales by state"]
    assert dependencies.plan_histories[1] == expected_history
    assert dependencies.sql_histories[1] == expected_history
    assert dependencies.response_histories[1] == expected_history
    assert second_turn.response.summary.assumptions == ["A1"]
