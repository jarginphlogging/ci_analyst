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


class HistorySpyDependencies:
    def __init__(self) -> None:
        self.classify_histories: list[list[str]] = []
        self.plan_histories: list[list[str]] = []
        self.sql_histories: list[list[str]] = []
        self.response_histories: list[list[str]] = []

    async def classify_route(self, request: ChatTurnRequest, history: list[str]) -> str:  # noqa: ARG002
        self.classify_histories.append(list(history))
        return "fast_path"

    async def create_plan(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> list[QueryPlanStep]:
        self.plan_histories.append(list(history))
        return [QueryPlanStep(id="step_1", goal="Retrieve primary KPI")]

    async def run_sql(  # noqa: ARG002
        self,
        request: ChatTurnRequest,
        plan: list[QueryPlanStep],
        history: list[str],
    ) -> list[SqlExecutionResult]:
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
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        self.response_histories.append(list(history))
        return AgentResponse(
            answer="Answer",
            confidence="high",
            whyItMatters="Why",
            metrics=[MetricPoint(label="metric", value=1.0, delta=0.1, unit="count")],
            evidence=[],
            insights=[Insight(id="i1", title="Insight", detail="Detail", importance="high")],
            suggestedQuestions=["Q1", "Q2", "Q3"],
            assumptions=["A1"],
            trace=[
                TraceStep(
                    id="t3",
                    title="Synthesize",
                    summary="done",
                    status="done",
                )
            ],
            dataTables=[
                DataTable(
                    id="table_1",
                    name="result_1",
                    columns=["segment", "prior", "current", "changeBps", "contribution"],
                    rows=[],
                    rowCount=0,
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

    assert dependencies.classify_histories[0] == []
    assert dependencies.plan_histories[0] == []
    assert dependencies.sql_histories[0] == []
    assert dependencies.response_histories[0] == []

    expected_history = ["Show sales by state"]
    assert dependencies.classify_histories[1] == expected_history
    assert dependencies.plan_histories[1] == expected_history
    assert dependencies.sql_histories[1] == expected_history
    assert dependencies.response_histories[1] == expected_history
    assert "Session memory depth: 2 turn(s)." in second_turn.response.assumptions
