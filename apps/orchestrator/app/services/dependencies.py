from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings
from app.models import (
    AgentResponse,
    ChatTurnRequest,
    QueryPlanStep,
    SqlExecutionResult,
    ValidationResult,
)
from app.providers.factory import build_live_provider_bundle
from app.providers.mock_provider import (
    mock_build_response,
    mock_classify_route,
    mock_create_plan,
    mock_run_sql,
    mock_validate_results,
)
from app.providers.protocols import LlmFn, SqlFn
from app.services.llm_json import parse_json_object
from app.services.semantic_model import SemanticModel, load_semantic_model
from app.services.stages import PlannerStage, SqlExecutionStage, SynthesisStage, ValidationStage, heuristic_route
from app.services.types import OrchestratorDependencies

@dataclass
class MockDependencies:
    async def classify_route(self, request: ChatTurnRequest) -> str:
        return await mock_classify_route(request)

    async def create_plan(self, request: ChatTurnRequest) -> list[QueryPlanStep]:
        return await mock_create_plan(request)

    async def run_sql(self, request: ChatTurnRequest, plan: list[QueryPlanStep]) -> list[SqlExecutionResult]:
        return await mock_run_sql(request, plan)

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        return await mock_validate_results(results)

    async def build_response(self, request: ChatTurnRequest, results: list[SqlExecutionResult]) -> AgentResponse:
        return await mock_build_response(request, results)


class RealDependencies:
    def __init__(
        self,
        *,
        llm_fn: Optional[LlmFn] = None,
        sql_fn: Optional[SqlFn] = None,
        model: Optional[SemanticModel] = None,
    ) -> None:
        provider_bundle = build_live_provider_bundle() if (llm_fn is None or sql_fn is None) else None
        self._llm_fn = llm_fn or (provider_bundle.llm_fn if provider_bundle else None)
        self._sql_fn = sql_fn or (provider_bundle.sql_fn if provider_bundle else None)
        if self._llm_fn is None or self._sql_fn is None:
            raise RuntimeError("Provider wiring failed to initialize.")
        self._model = model or load_semantic_model()
        self._route_cache: dict[str, str] = {}
        self._assumption_cache: dict[str, list[str]] = {}
        self._planner_stage = PlannerStage(model=self._model, ask_llm_json=self._ask_llm_json)
        self._sql_stage = SqlExecutionStage(model=self._model, ask_llm_json=self._ask_llm_json, sql_fn=self._sql_fn)
        self._validation_stage = ValidationStage(max_row_limit=self._model.policy.max_row_limit)
        self._synthesis_stage = SynthesisStage(ask_llm_json=self._ask_llm_json)

    async def _ask_llm_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        response = await self._llm_fn(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=settings.real_llm_temperature,
            max_tokens=max_tokens,
            response_json=True,
        )
        return parse_json_object(response)

    async def classify_route(self, request: ChatTurnRequest) -> str:
        route = await self._planner_stage.classify_route(request.message)
        self._route_cache[request.message] = route
        return route

    async def create_plan(self, request: ChatTurnRequest) -> list[QueryPlanStep]:
        route = self._route_cache.get(request.message) or heuristic_route(request.message)
        return await self._planner_stage.create_plan(request.message, route)

    async def run_sql(self, request: ChatTurnRequest, plan: list[QueryPlanStep]) -> list[SqlExecutionResult]:
        route = self._route_cache.get(request.message) or heuristic_route(request.message)
        results, accumulated_assumptions = await self._sql_stage.run_sql(
            message=request.message,
            route=route,
            plan=plan,
        )
        self._assumption_cache[request.message] = accumulated_assumptions
        return results

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        return self._validation_stage.validate_results(results)

    async def build_response(self, request: ChatTurnRequest, results: list[SqlExecutionResult]) -> AgentResponse:
        route = self._route_cache.get(request.message) or heuristic_route(request.message)
        return await self._synthesis_stage.build_response(
            message=request.message,
            route=route,
            results=results,
            prior_assumptions=self._assumption_cache.get(request.message, []),
        )


def create_dependencies() -> OrchestratorDependencies:
    if settings.use_mock_providers:
        return MockDependencies()
    provider_bundle = build_live_provider_bundle()
    return RealDependencies(
        llm_fn=provider_bundle.llm_fn,
        sql_fn=provider_bundle.sql_fn,
    )
