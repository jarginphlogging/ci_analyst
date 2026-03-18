from __future__ import annotations

import logging
import json
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel

from app.config import settings
from app.models import (
    AgentResponse,
    ChatTurnRequest,
    SqlExecutionResult,
    ValidationResult,
)
from app.providers.factory import build_provider_bundle
from app.providers.protocols import AnalystFn, LlmFn, SqlFn
from app.services.llm_json import parse_json_object
from app.services.llm_schemas import (
    PlannerResponsePayload,
    SqlGenerationResponsePayload,
    SynthesisResponsePayload,
)
from app.services.llm_trace import current_llm_trace_stage, record_llm_trace
from app.services.semantic_model import SemanticModel, load_semantic_model
from app.services.semantic_policy import SemanticPolicy, load_semantic_policy
from app.services.stages import (
    PlannerBlockedError,
    PlannerStage,
    SqlExecutionStage,
    SynthesisStage,
    ValidationStage,
)
from app.services.types import OrchestratorDependencies, TurnExecutionContext

ProgressCallback = Optional[Callable[[str], Optional[Awaitable[None]]]]
logger = logging.getLogger(__name__)


class RealDependencies:
    def __init__(
        self,
        *,
        llm_fn: Optional[LlmFn] = None,
        sql_fn: Optional[SqlFn] = None,
        analyst_fn: Optional[AnalystFn] = None,
        model: Optional[SemanticModel] = None,
        policy: Optional[SemanticPolicy] = None,
    ) -> None:
        provider_bundle = None
        if llm_fn is None or sql_fn is None or analyst_fn is None:
            provider_bundle = build_provider_bundle(settings.provider_mode)
        self._llm_fn = llm_fn or (provider_bundle.llm_fn if provider_bundle else None)
        self._sql_fn = sql_fn or (provider_bundle.sql_fn if provider_bundle else None)
        self._analyst_fn = analyst_fn if analyst_fn is not None else (
            provider_bundle.analyst_fn if provider_bundle else None
        )
        if self._llm_fn is None or self._sql_fn is None:
            raise RuntimeError("Provider wiring failed to initialize.")
        self._model = model or load_semantic_model()
        self._policy = policy or load_semantic_policy()
        self._planner_stage = PlannerStage(model=self._model, ask_llm_json=self._ask_planner_payload)
        self._sql_stage = SqlExecutionStage(
            model=self._model,
            policy=self._policy,
            ask_llm_json=self._ask_sql_generation_payload,
            sql_fn=self._sql_fn,
            analyst_fn=self._analyst_fn,
        )
        self._validation_stage = ValidationStage(max_row_limit=self._policy.max_row_limit)
        self._synthesis_stage = SynthesisStage(ask_llm_json=self._ask_synthesis_payload)
        self._llm_provider_label = self._resolve_llm_provider_label()

    def _resolve_llm_provider_label(self) -> str:
        module_name = getattr(self._llm_fn, "__module__", "")
        if "azure_openai" in module_name:
            return "azure_openai"
        if "anthropic_bedrock" in module_name:
            return "anthropic_bedrock"
        if "anthropic_llm" in module_name:
            return "anthropic_direct"
        try:
            provider = settings.llm_provider
        except RuntimeError:
            provider = ""
        if provider:
            return provider
        return "llm"

    async def _ask_planner_payload(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        return await self._ask_llm_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            output_model=PlannerResponsePayload,
            schema_name="planner_response",
        )

    async def _ask_sql_generation_payload(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        return await self._ask_llm_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            output_model=SqlGenerationResponsePayload,
            schema_name="sql_generation_response",
        )

    async def _ask_synthesis_payload(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        return await self._ask_llm_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            output_model=SynthesisResponsePayload,
            schema_name="synthesis_response",
        )

    async def _ask_llm_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        output_model: type[BaseModel],
        schema_name: str,
    ) -> dict[str, Any]:
        raw_response: str | None = None
        started_at = perf_counter()
        stage_name = "unknown_stage"
        stage_metadata: dict[str, Any] = {}
        stage = current_llm_trace_stage()
        if stage is not None:
            stage_name, stage_metadata = stage
        logger.info(
            "LLM call started",
            extra={
                "event": "llm.call.started",
                "provider": settings.provider_mode,
                "stage": stage_name,
                "structuredMode": True,
                "schemaName": schema_name,
                "maxTokens": max_tokens,
                "temperature": settings.real_llm_temperature,
                "systemPromptChars": len(system_prompt),
                "userPromptChars": len(user_prompt),
                "stageMetadata": stage_metadata,
            },
        )
        try:
            llm_kwargs: dict[str, Any] = {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": settings.real_llm_temperature,
                "max_tokens": max_tokens,
                "response_schema": output_model.model_json_schema(),
                "response_schema_name": schema_name,
            }

            llm_response = await self._llm_fn(**llm_kwargs)

            payload: dict[str, Any]
            if isinstance(llm_response, dict):
                payload = llm_response
                raw_response = json.dumps(llm_response, ensure_ascii=True)
            elif isinstance(llm_response, str):
                raw_response = llm_response
                payload = parse_json_object(llm_response)
            else:
                raise RuntimeError("LLM provider returned unsupported response type.")

            parsed_model = output_model.model_validate(payload)
            parsed_response = parsed_model.model_dump(mode="json", exclude_none=True)
            record_llm_trace(
                provider=self._llm_provider_label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=settings.real_llm_temperature,
                raw_response=raw_response,
                parsed_response=parsed_response,
            )
            logger.info(
                "LLM call completed",
                extra={
                    "event": "llm.call.completed",
                    "provider": settings.provider_mode,
                    "stage": stage_name,
                    "structuredMode": True,
                    "schemaName": schema_name,
                    "durationMs": round((perf_counter() - started_at) * 1000, 2),
                    "responseChars": len(raw_response or ""),
                },
            )
            return parsed_response
        except TypeError as error:
            if "unexpected keyword argument" in str(error):
                logger.exception(
                    "LLM provider does not support structured output arguments",
                    extra={
                        "event": "llm.call.failed_structured_unsupported",
                        "provider": settings.provider_mode,
                        "stage": stage_name,
                        "schemaName": schema_name,
                    },
                )
                raise RuntimeError("Configured provider does not support structured output parameters.") from error
            record_llm_trace(
                provider=self._llm_provider_label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=settings.real_llm_temperature,
                raw_response=raw_response,
                error=str(error),
            )
            logger.exception(
                "LLM call failed",
                extra={
                "event": "llm.call.failed",
                "provider": settings.provider_mode,
                "stage": stage_name,
                "structuredMode": True,
                "schemaName": schema_name,
                "durationMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )
            raise
        except Exception as error:
            record_llm_trace(
                provider=self._llm_provider_label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=settings.real_llm_temperature,
                raw_response=raw_response,
                error=str(error),
            )
            logger.exception(
                "LLM call failed",
                extra={
                "event": "llm.call.failed",
                "provider": settings.provider_mode,
                "stage": stage_name,
                "structuredMode": True,
                "schemaName": schema_name,
                "durationMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )
            raise

    async def create_plan(
        self,
        request: ChatTurnRequest,
        history: list[str],
    ) -> TurnExecutionContext:
        logger.info(
            "Creating plan",
            extra={
                "event": "dependencies.create_plan.started",
                "historyDepth": len(history),
                "messageChars": len(request.message),
            },
        )
        decision = await self._planner_stage.create_plan(request.message, history)
        if decision.stop_reason != "none":
            logger.info(
                "Planner returned blocked decision",
                extra={
                    "event": "dependencies.create_plan.blocked",
                    "stopReason": decision.stop_reason,
                },
            )
            raise PlannerBlockedError(
                stop_reason=decision.stop_reason,
                user_message=decision.stop_message or "",
            )
        logger.info(
            "Plan created",
            extra={
                "event": "dependencies.create_plan.completed",
                "stepCount": len(decision.steps),
            },
        )
        return TurnExecutionContext(
            plan=decision.steps,
            presentation_intent=decision.presentation_intent,
            temporal_scope=decision.temporal_scope,
        )

    async def run_sql(
        self,
        request: ChatTurnRequest,
        context: TurnExecutionContext,
        history: list[str],
        progress_callback: ProgressCallback = None,
    ) -> list[SqlExecutionResult]:
        logger.info(
            "Running SQL stage",
            extra={
                "event": "dependencies.run_sql.started",
                "stepCount": len(context.plan),
            },
        )
        try:
            sql_outcome = await self._sql_stage.run_sql(
                message=request.message,
                plan=context.plan,
                history=history,
                conversation_id=str(request.sessionId or "anonymous"),
                temporal_scope=context.temporal_scope,
                progress_callback=progress_callback,
            )
            context.sql_interpretation_notes = list(sql_outcome.interpretation_notes)
            context.sql_caveats = list(sql_outcome.caveats)
            context.sql_assumptions = [
                *context.sql_interpretation_notes,
                *context.sql_caveats,
                *sql_outcome.assumptions,
            ][:8]
            logger.info(
                "SQL stage returned results",
                extra={
                    "event": "dependencies.run_sql.completed",
                    "queryCount": len(sql_outcome.results),
                    "totalRows": sum(result.rowCount for result in sql_outcome.results),
                },
            )
            return sql_outcome.results
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
        logger.info(
            "Building final response",
            extra={
                "event": "dependencies.build_response.started",
                "resultCount": len(results),
            },
        )
        return await self._synthesis_stage.build_response(
            message=request.message,
            plan=context.plan,
            presentation_intent=context.presentation_intent,
            temporal_scope=context.temporal_scope,
            results=results,
            prior_interpretation_notes=context.sql_interpretation_notes,
            prior_caveats=context.sql_caveats,
            prior_assumptions=context.sql_assumptions,
            history=history,
        )


def create_dependencies() -> OrchestratorDependencies:
    provider_bundle = build_provider_bundle(settings.provider_mode)
    return RealDependencies(
        llm_fn=provider_bundle.llm_fn,
        sql_fn=provider_bundle.sql_fn,
        analyst_fn=provider_bundle.analyst_fn,
    )
