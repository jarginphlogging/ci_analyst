from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from app.models import AgentResponse, ChatTurnRequest, PresentationIntent, QueryPlanStep, SqlExecutionResult, TemporalScope, ValidationResult


@dataclass
class TurnExecutionContext:
    plan: list[QueryPlanStep]
    presentation_intent: PresentationIntent = field(
        default_factory=lambda: PresentationIntent(displayType="table", tableStyle="simple")
    )
    temporal_scope: TemporalScope | None = None
    sql_interpretation_notes: list[str] = field(default_factory=list)
    sql_caveats: list[str] = field(default_factory=list)
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
