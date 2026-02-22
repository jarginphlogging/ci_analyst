from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar
from uuid import uuid4

from app.models import AgentResponse, ChatTurnRequest, SqlExecutionResult, StreamResult, TurnResult, ValidationResult, now_iso
from app.services.stages.synthesis_stage import build_incremental_answer_deltas
from app.services.types import OrchestratorDependencies

T = TypeVar("T")
ProgressCallback = Callable[[str], Awaitable[None]]


class ConversationalOrchestrator:
    def __init__(self, dependencies: OrchestratorDependencies):
        self._dependencies = dependencies
        self._session_history: dict[str, list[str]] = {}

    def _session_context(self, request: ChatTurnRequest) -> tuple[str, list[str]]:
        session_id = str(request.sessionId or "anonymous")
        history = self._session_history.get(session_id, [])
        prior_history = history[-8:]
        history.append(request.message)
        self._session_history[session_id] = history[-12:]
        return session_id, prior_history

    async def _run_with_heartbeat(
        self,
        *,
        operation: Callable[[], Awaitable[T]],
        progress_callback: ProgressCallback,
        heartbeat_message: str,
        interval_seconds: float = 1.5,
    ) -> T:
        task = asyncio.create_task(operation())
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=interval_seconds)
            except asyncio.TimeoutError:
                await progress_callback(heartbeat_message)

    async def _execute_pipeline(
        self,
        request: ChatTurnRequest,
        prior_history: list[str],
        progress_callback: ProgressCallback,
    ) -> tuple[str, list[SqlExecutionResult], ValidationResult]:
        await progress_callback("Selecting fast path vs deep path reasoning")
        route = await self._run_with_heartbeat(
            operation=lambda: self._dependencies.classify_route(request, prior_history),
            progress_callback=progress_callback,
            heartbeat_message="Classifying intent...",
        )

        await progress_callback("Building governed plan and SQL")
        plan = await self._run_with_heartbeat(
            operation=lambda: self._dependencies.create_plan(request, prior_history),
            progress_callback=progress_callback,
            heartbeat_message="Building plan...",
        )
        await progress_callback(f"Plan ready with {len(plan)} step(s)")

        await progress_callback("Executing SQL and retrieving result tables")
        results = await self._run_with_heartbeat(
            operation=lambda: self._dependencies.run_sql(
                request,
                plan,
                prior_history,
                progress_callback=progress_callback,
            ),
            progress_callback=progress_callback,
            heartbeat_message="Executing governed SQL...",
        )

        await progress_callback("Running numeric QA and consistency checks")
        validation = await self._dependencies.validate_results(results)

        if not validation.passed:
            raise RuntimeError("Result validation failed.")
        return route, results, validation

    def _finalize_response(
        self,
        *,
        response: AgentResponse,
        validation: ValidationResult,
        route: str,
        session_depth: int,
    ) -> AgentResponse:
        response.trace = [
            (step.model_copy(update={"qualityChecks": validation.checks}) if step.id == "t3" else step)
            for step in response.trace
        ]

        assumptions = [
            *response.assumptions,
            "Deep path was selected for multi-step reasoning." if route == "deep_path" else "Fast path was selected for low latency.",
            f"Session memory depth: {session_depth} turn(s).",
        ]
        deduped: list[str] = []
        for item in assumptions:
            if item not in deduped:
                deduped.append(item)
        response.assumptions = deduped
        return response

    async def run_turn(self, request: ChatTurnRequest) -> TurnResult:
        session_id, prior_history = self._session_context(request)

        async def _noop_progress(_: str) -> None:
            return None

        route, results, validation = await self._execute_pipeline(request, prior_history, _noop_progress)

        response = await self._dependencies.build_response(request, results, prior_history)
        response = self._finalize_response(
            response=response,
            validation=validation,
            route=route,
            session_depth=len(self._session_history.get(session_id, [])),
        )

        return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

    async def stream_events(self, request: ChatTurnRequest) -> AsyncIterator[dict[str, Any]]:
        session_id, prior_history = self._session_context(request)
        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await event_queue.put(event)

        async def progress(message: str) -> None:
            await emit({"type": "status", "message": message})

        async def worker() -> None:
            try:
                await progress("Understanding query intent and scope")
                route, results, validation = await self._execute_pipeline(
                    request,
                    prior_history,
                    progress,
                )

                await progress("Preparing initial answer from retrieved data")
                fast_response = await self._run_with_heartbeat(
                    operation=lambda: self._dependencies.build_fast_response(request, results, prior_history),
                    progress_callback=progress,
                    heartbeat_message="Building initial answer...",
                )
                fast_response = self._finalize_response(
                    response=fast_response,
                    validation=validation,
                    route=route,
                    session_depth=len(self._session_history.get(session_id, [])),
                )
                await emit({"type": "response", "phase": "draft", "response": fast_response.model_dump()})

                await progress("Generating final narrative and recommendations")
                final_response = await self._run_with_heartbeat(
                    operation=lambda: self._dependencies.build_response(request, results, prior_history),
                    progress_callback=progress,
                    heartbeat_message="Synthesizing narrative...",
                )
                final_response = self._finalize_response(
                    response=final_response,
                    validation=validation,
                    route=route,
                    session_depth=len(self._session_history.get(session_id, [])),
                )

                for delta in build_incremental_answer_deltas(fast_response.answer, final_response.answer):
                    await emit({"type": "answer_delta", "delta": delta})

                await progress("Finalizing response payload and audit trace")
                await emit({"type": "response", "phase": "final", "response": final_response.model_dump()})
                await emit({"type": "done"})
            except Exception as error:  # noqa: BLE001
                await emit({"type": "error", "message": str(error)})
                await emit({"type": "done"})
            finally:
                await event_queue.put(None)

        worker_task = asyncio.create_task(worker())
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not worker_task.done():
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    async def run_stream(self, request: ChatTurnRequest) -> StreamResult:
        events: list[dict[str, Any]] = []
        final_response: AgentResponse | None = None

        async for event in self.stream_events(request):
            events.append(event)
            if event.get("type") == "response":
                response_payload = event.get("response")
                if isinstance(response_payload, dict):
                    final_response = AgentResponse.model_validate(response_payload)

        if final_response is None:
            raise RuntimeError("Streaming ended before a response payload was produced.")

        return StreamResult(
            events=events,
            turn=TurnResult(
                turnId=str(uuid4()),
                createdAt=now_iso(),
                response=final_response,
            ),
        )
