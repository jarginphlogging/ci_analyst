from __future__ import annotations

from uuid import uuid4

from app.models import ChatTurnRequest, StreamResult, TurnResult, now_iso
from app.services.types import OrchestratorDependencies


class ConversationalOrchestrator:
    def __init__(self, dependencies: OrchestratorDependencies):
        self._dependencies = dependencies
        self._session_history: dict[str, list[str]] = {}

    async def run_turn(self, request: ChatTurnRequest) -> TurnResult:
        session_id = str(request.sessionId or "anonymous")
        history = self._session_history.get(session_id, [])
        prior_history = history[-8:]
        history.append(request.message)
        self._session_history[session_id] = history[-12:]

        route = await self._dependencies.classify_route(request, prior_history)
        plan = await self._dependencies.create_plan(request, prior_history)
        results = await self._dependencies.run_sql(request, plan, prior_history)
        validation = await self._dependencies.validate_results(results)

        if not validation.passed:
            raise RuntimeError("Result validation failed.")

        response = await self._dependencies.build_response(request, results, prior_history)

        response.trace = [
            (
                step.model_copy(update={"qualityChecks": validation.checks})
                if step.id == "t3"
                else step
            )
            for step in response.trace
        ]

        response.assumptions = [
            *response.assumptions,
            "Deep path was selected for multi-step reasoning."
            if route == "deep_path"
            else "Fast path was selected for low latency.",
            f"Session memory depth: {len(self._session_history.get(session_id, []))} turn(s).",
        ]

        return TurnResult(turnId=str(uuid4()), createdAt=now_iso(), response=response)

    async def run_stream(self, request: ChatTurnRequest) -> StreamResult:
        events: list[dict[str, object]] = [
            {"type": "status", "message": "Understanding query intent and scope"},
            {"type": "status", "message": "Selecting fast path vs deep path reasoning"},
            {"type": "status", "message": "Resolving latest RESP_DATE context from semantic model"},
            {"type": "status", "message": "Building governed plan and SQL"},
            {"type": "status", "message": "Executing SQL and retrieving result tables"},
        ]

        turn = await self.run_turn(request)

        events.append({"type": "status", "message": "Running numeric QA and consistency checks"})
        events.append({"type": "status", "message": "Ranking insights by impact and confidence"})

        for token in turn.response.answer.split(" "):
            events.append({"type": "answer_delta", "delta": f"{token} "})

        events.append({"type": "status", "message": "Finalizing response payload and audit trace"})
        events.append({"type": "response", "response": turn.response.model_dump()})
        events.append({"type": "done"})

        return StreamResult(events=events, turn=turn)
