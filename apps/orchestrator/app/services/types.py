from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from app.models import AnalysisType, AgentResponse, ChatTurnRequest, QueryPlanStep, SqlExecutionResult, ValidationResult


@dataclass
class TurnExecutionContext:
    route: str
    plan: list[QueryPlanStep]
    analysis_type: AnalysisType = "aggregation_summary_stats"
    secondary_analysis_type: AnalysisType | None = None
    sql_assumptions: list[str] = field(default_factory=list)
    sql_retry_feedback: list[dict[str, Any]] = field(default_factory=list)


class OrchestratorDependencies(Protocol):
    async def create_plan(
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> TurnExecutionContext: ...

    async def run_sql(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
    ) -> list[SqlExecutionResult]: ...

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult: ...

    async def build_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse: ...

    async def build_fast_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse: ...
