from __future__ import annotations

from typing import Protocol

from app.models import AgentResponse, ChatTurnRequest, QueryPlanStep, SqlExecutionResult, ValidationResult


class OrchestratorDependencies(Protocol):
    async def classify_route(self, request: ChatTurnRequest) -> str: ...

    async def create_plan(self, request: ChatTurnRequest) -> list[QueryPlanStep]: ...

    async def run_sql(self, request: ChatTurnRequest, plan: list[QueryPlanStep]) -> list[SqlExecutionResult]: ...

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult: ...

    async def build_response(self, request: ChatTurnRequest, results: list[SqlExecutionResult]) -> AgentResponse: ...
