from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.config import settings
from app.models import QueryPlanStep
from app.prompts.templates import plan_prompt, route_prompt
from app.services.semantic_model import SemanticModel

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


def heuristic_route(message: str) -> str:
    query = message.lower()
    if any(keyword in query for keyword in ["why", "driver", "compare", "versus", "trend", "root cause"]):
        return "deep_path"
    return "fast_path"


def fallback_plan(route: str) -> list[QueryPlanStep]:
    if route == "fast_path":
        return [
            QueryPlanStep(id="step_1", goal="Retrieve primary KPI by relevant segment and recent periods"),
            QueryPlanStep(id="step_2", goal="Return top movers and concentration"),
        ]
    return [
        QueryPlanStep(id="step_1", goal="Retrieve KPI trend for requested question scope"),
        QueryPlanStep(id="step_2", goal="Break KPI into segment-level drivers"),
        QueryPlanStep(id="step_3", goal="Compare severity versus volume and rank insights"),
    ]


class PlannerStage:
    def __init__(self, *, model: SemanticModel, ask_llm_json: AskLlmJsonFn) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json

    async def classify_route(self, message: str) -> str:
        system_prompt, user_prompt = route_prompt(message, [])
        route = heuristic_route(message)
        try:
            payload = await self._ask_llm_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=220,
            )
            candidate = str(payload.get("route", "")).strip()
            if candidate in {"fast_path", "deep_path"}:
                route = candidate
        except Exception:
            route = heuristic_route(message)
        return route

    async def create_plan(self, message: str, route: str) -> list[QueryPlanStep]:
        max_steps = settings.real_deep_plan_steps if route == "deep_path" else settings.real_fast_plan_steps
        max_steps = max(1, max_steps)

        system_prompt, user_prompt = plan_prompt(message, route, self._model, max_steps)

        try:
            payload = await self._ask_llm_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=min(settings.real_llm_max_tokens, 900),
            )
            raw_steps = payload.get("steps", [])
            if isinstance(raw_steps, list) and raw_steps:
                steps: list[QueryPlanStep] = []
                for index, entry in enumerate(raw_steps[:max_steps], start=1):
                    if not isinstance(entry, dict):
                        continue
                    goal = str(entry.get("goal", "")).strip()
                    if not goal:
                        continue
                    steps.append(QueryPlanStep(id=f"step_{index}", goal=goal))
                if steps:
                    return steps
        except Exception:
            pass

        return fallback_plan(route)[:max_steps]
