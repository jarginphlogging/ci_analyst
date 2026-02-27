from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import (
    AgentResponse,
    ChatTurnRequest,
    SqlExecutionResult,
    ValidationResult,
)
from app.providers.factory import build_provider_bundle
from app.providers.mock_provider import (
    mock_build_response,
    mock_create_plan,
    mock_run_sql,
    mock_validate_results,
)
from app.providers.protocols import AnalystFn, LlmFn, SqlFn
from app.services.llm_json import parse_json_object
from app.services.llm_trace import record_llm_trace
from app.services.semantic_model import SemanticModel, load_semantic_model
from app.services.stages import (
    PlannerBlockedError,
    PlannerStage,
    SqlExecutionStage,
    SynthesisStage,
    ValidationStage,
)
from app.services.types import OrchestratorDependencies, TurnExecutionContext

ProgressCallback = Optional[Callable[[str], Optional[Awaitable[None]]]]
EXECUTION_MODE = "standard"


@dataclass
class MockDependencies:
    async def create_plan(
        self,
        request: ChatTurnRequest,
        history: list[str],  # noqa: ARG002
    ) -> TurnExecutionContext:
        plan = await mock_create_plan(request)
        return TurnExecutionContext(route=EXECUTION_MODE, plan=plan)

    async def run_sql(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],  # noqa: ARG002
        progress_callback: ProgressCallback = None,  # noqa: ARG002
    ) -> list[SqlExecutionResult]:
        return await mock_run_sql(request, context.plan)

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        return await mock_validate_results(results)

    async def build_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,  # noqa: ARG002
        results: list[SqlExecutionResult],
        history: list[str],  # noqa: ARG002
    ) -> AgentResponse:
        return await mock_build_response(request, results)

    async def build_fast_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,  # noqa: ARG002
        results: list[SqlExecutionResult],
        history: list[str],  # noqa: ARG002
    ) -> AgentResponse:
        return await mock_build_response(request, results)


class RealDependencies:
    def __init__(
        self,
        *,
        llm_fn: Optional[LlmFn] = None,
        sql_fn: Optional[SqlFn] = None,
        analyst_fn: Optional[AnalystFn] = None,
        model: Optional[SemanticModel] = None,
    ) -> None:
        provider_bundle = None
        if llm_fn is None or sql_fn is None or analyst_fn is None:
            mode = settings.provider_mode
            if mode == "mock":
                mode = "prod"
            provider_bundle = build_provider_bundle(mode)
        self._llm_fn = llm_fn or (provider_bundle.llm_fn if provider_bundle else None)
        self._sql_fn = sql_fn or (provider_bundle.sql_fn if provider_bundle else None)
        self._analyst_fn = analyst_fn if analyst_fn is not None else (
            provider_bundle.analyst_fn if provider_bundle else None
        )
        if self._llm_fn is None or self._sql_fn is None:
            raise RuntimeError("Provider wiring failed to initialize.")
        self._model = model or load_semantic_model()
        self._planner_stage = PlannerStage(model=self._model, ask_llm_json=self._ask_llm_json)
        self._sql_stage = SqlExecutionStage(
            model=self._model,
            ask_llm_json=self._ask_llm_json,
            sql_fn=self._sql_fn,
            analyst_fn=self._analyst_fn,
        )
        self._validation_stage = ValidationStage(max_row_limit=self._model.policy.max_row_limit)
        self._synthesis_stage = SynthesisStage(ask_llm_json=self._ask_llm_json)

    async def _ask_llm_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        raw_response: str | None = None
        try:
            raw_response = await self._llm_fn(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.real_llm_temperature,
                max_tokens=max_tokens,
                response_json=True,
            )
            parsed_response = parse_json_object(raw_response)
            record_llm_trace(
                provider="llm",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=settings.real_llm_temperature,
                raw_response=raw_response,
                parsed_response=parsed_response,
            )
            return parsed_response
        except Exception as error:
            record_llm_trace(
                provider="llm",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=settings.real_llm_temperature,
                raw_response=raw_response,
                error=str(error),
            )
            raise

    async def create_plan(
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> TurnExecutionContext:
        decision = await self._planner_stage.create_plan(request.message, history)
        if decision.stop_reason != "none":
            raise PlannerBlockedError(
                stop_reason=decision.stop_reason,
                user_message=decision.stop_message or "Unable to process request.",
            )
        return TurnExecutionContext(
            route=EXECUTION_MODE,
            plan=decision.steps,
            analysis_type=decision.analysis_type,
            secondary_analysis_type=decision.secondary_analysis_type,
        )

    async def run_sql(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback: ProgressCallback = None,
    ) -> list[SqlExecutionResult]:
        try:
            results, accumulated_assumptions = await self._sql_stage.run_sql(
                message=request.message,
                route=context.route,
                plan=context.plan,
                history=history,
                conversation_id=str(request.sessionId or "anonymous"),
                progress_callback=progress_callback,
            )
            context.sql_assumptions = accumulated_assumptions
            return results
        finally:
            context.sql_retry_feedback = self._sql_stage.latest_retry_feedback

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        return self._validation_stage.validate_results(results)

    async def build_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        return await self._synthesis_stage.build_response(
            message=request.message,
            route=context.route,
            plan=context.plan,
            analysis_type=context.analysis_type,
            secondary_analysis_type=context.secondary_analysis_type,
            results=results,
            prior_assumptions=context.sql_assumptions,
            history=history,
        )

    async def build_fast_response(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        results: list[SqlExecutionResult],
        history: list[str],
    ) -> AgentResponse:
        return await self._synthesis_stage.build_fast_response(
            message=request.message,
            route=context.route,
            plan=context.plan,
            analysis_type=context.analysis_type,
            secondary_analysis_type=context.secondary_analysis_type,
            results=results,
            prior_assumptions=context.sql_assumptions,
            history=history,
        )


def create_dependencies() -> OrchestratorDependencies:
    if settings.provider_mode == "mock":
        return MockDependencies()
    provider_bundle = build_provider_bundle(settings.provider_mode)
    return RealDependencies(
        llm_fn=provider_bundle.llm_fn,
        sql_fn=provider_bundle.sql_fn,
        analyst_fn=provider_bundle.analyst_fn,
    )
