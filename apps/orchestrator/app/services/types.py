from __future__ import annotations

from typing import Protocol

from app.models import AgentResponse, ChatTurnRequest, QueryPlanStep, SqlExecutionResult, ValidationResult


class OrchestratorDependencies(Protocol):
    async def classify_route(self, request: ChatTurnRequest, history: list[str]) -> str: ...

    async def create_plan(self, request: ChatTurnRequest, history: list[str]) -> list[QueryPlanStep]: ...

    async def run_sql(
        self,
        request: ChatTurnRequest,
        plan: list[QueryPlanStep],
        history: list[str],
    ) -> list[SqlExecutionResult]: ...

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult: ...

    async def build_response(
        self,
        request: ChatTurnRequest,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse: ...
