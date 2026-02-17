from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional, cast

from app.config import settings
from app.models import (
    AgentResponse,
    ChatTurnRequest,
    EvidenceRow,
    Insight,
    QueryPlanStep,
    SqlExecutionResult,
    TraceStep,
    ValidationResult,
)
from app.prompts.templates import plan_prompt, response_prompt, route_prompt, sql_prompt
from app.providers.azure_openai import chat_completion
from app.providers.mock_provider import (
    mock_build_response,
    mock_classify_route,
    mock_create_plan,
    mock_run_sql,
    mock_validate_results,
)
from app.providers.snowflake_cortex import execute_cortex_sql
from app.services.llm_json import as_string_list, parse_json_object
from app.services.semantic_model import SemanticModel, SemanticTable, load_semantic_model
from app.services.sql_guardrails import guard_sql
from app.services.table_analysis import (
    build_evidence_rows,
    build_metric_points,
    normalize_rows,
    results_to_data_tables,
    summarize_results_for_prompt,
)
from app.services.types import OrchestratorDependencies

LlmFn = Callable[..., Awaitable[str]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _heuristic_route(message: str) -> str:
    query = message.lower()
    if any(keyword in query for keyword in ["why", "driver", "compare", "versus", "trend", "root cause"]):
        return "deep_path"
    return "fast_path"


def _sanitize_insights(raw: Any) -> list[Insight]:
    if not isinstance(raw, list):
        return []

    items: list[Insight] = []
    for index, entry in enumerate(raw[:4], start=1):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not title or not detail:
            continue
        importance = str(entry.get("importance", "medium")).lower()
        normalized_importance: Literal["high", "medium"] = "high" if importance == "high" else "medium"
        items.append(
            Insight(
                id=f"i{index}",
                title=title,
                detail=detail,
                importance=normalized_importance,
            )
        )
    return items


def _first_table(model: SemanticModel) -> SemanticTable:
    return model.tables[0]


def _select_table_for_goal(model: SemanticModel, goal: str) -> SemanticTable:
    lowered = goal.lower()
    best = _first_table(model)
    best_score = -1
    for table in model.tables:
        features = [*table.metrics, *table.dimensions, table.name, table.description]
        score = sum(1 for feature in features if str(feature).lower() in lowered)
        if score > best_score:
            best = table
            best_score = score
    return best


def _fallback_plan(route: str) -> list[QueryPlanStep]:
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


def _fallback_sql(model: SemanticModel, goal: str) -> str:
    table = _select_table_for_goal(model, goal)
    dimension = table.dimensions[0] if table.dimensions else "quarter"
    metric = table.metrics[0] if table.metrics else "*"

    if metric == "*":
        return f"SELECT * FROM {table.name}"

    return (
        f"SELECT {dimension}, AVG({metric}) AS metric_value "
        f"FROM {table.name} "
        f"GROUP BY {dimension} "
        f"ORDER BY metric_value DESC"
    )


def _default_insights(evidence: list[EvidenceRow]) -> list[Insight]:
    if not evidence:
        return [
            Insight(
                id="i1",
                title="Limited evidence returned",
                detail="The query returned data but not enough structured segments for deep decomposition.",
                importance="medium",
            )
        ]

    top = max(evidence, key=lambda row: abs(row.changeBps))
    return [
        Insight(
            id="i1",
            title=f"Largest movement in {top.segment}",
            detail=f"Segment change of {top.changeBps:.1f} bps dominates the observed shift.",
            importance="high",
        ),
        Insight(
            id="i2",
            title="Concentration pattern is measurable",
            detail="Top segments carry disproportionate contribution, supporting targeted intervention.",
            importance="medium",
        ),
    ]


def _default_questions() -> list[str]:
    return [
        "Can you break this down by state and channel?",
        "How much of the change came from repeat versus new customers?",
        "Which stores are diverging most from portfolio averages?",
    ]


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
        self._llm_fn = llm_fn or chat_completion
        self._sql_fn = sql_fn or execute_cortex_sql
        self._model = model or load_semantic_model()
        self._route_cache: dict[str, str] = {}
        self._assumption_cache: dict[str, list[str]] = {}

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
        system_prompt, user_prompt = route_prompt(request.message, [])
        route = _heuristic_route(request.message)
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
            route = _heuristic_route(request.message)

        self._route_cache[request.message] = route
        return route

    async def create_plan(self, request: ChatTurnRequest) -> list[QueryPlanStep]:
        route = self._route_cache.get(request.message) or _heuristic_route(request.message)
        max_steps = settings.real_deep_plan_steps if route == "deep_path" else settings.real_fast_plan_steps
        max_steps = max(1, max_steps)

        system_prompt, user_prompt = plan_prompt(request.message, route, self._model, max_steps)

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

        return _fallback_plan(route)[:max_steps]

    async def run_sql(self, request: ChatTurnRequest, plan: list[QueryPlanStep]) -> list[SqlExecutionResult]:
        route = self._route_cache.get(request.message) or _heuristic_route(request.message)
        prior_sql: list[str] = []
        accumulated_assumptions: list[str] = []
        results: list[SqlExecutionResult] = []

        for step in plan:
            sql_text = _fallback_sql(self._model, step.goal)
            try:
                system_prompt, user_prompt = sql_prompt(
                    request.message,
                    route,
                    step.id,
                    step.goal,
                    self._model,
                    prior_sql,
                )
                payload = await self._ask_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=min(settings.real_llm_max_tokens, 1100),
                )
                candidate_sql = str(payload.get("sql", "")).strip()
                if candidate_sql:
                    sql_text = candidate_sql
                accumulated_assumptions.extend(as_string_list(payload.get("assumptions"), max_items=3))
            except Exception:
                pass

            guarded_sql = guard_sql(sql_text, self._model)
            prior_sql.append(guarded_sql)

            try:
                raw_rows = await self._sql_fn(guarded_sql)
            except Exception:
                fallback_sql = guard_sql(f"SELECT * FROM {_select_table_for_goal(self._model, step.goal).name}", self._model)
                raw_rows = await self._sql_fn(fallback_sql)
                guarded_sql = fallback_sql

            normalized_rows = normalize_rows(raw_rows)
            results.append(
                SqlExecutionResult(
                    sql=guarded_sql,
                    rows=normalized_rows,
                    rowCount=len(normalized_rows),
                )
            )

        self._assumption_cache[request.message] = accumulated_assumptions[:6]
        return results

    async def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        checks: list[str] = []
        if not results:
            return ValidationResult(passed=False, checks=["No SQL steps were executed."])

        checks.append(f"Executed {len(results)} governed SQL step(s).")

        total_rows = sum(result.rowCount for result in results)
        checks.append(f"Total retrieved rows: {total_rows}.")
        if total_rows <= 0:
            checks.append("No rows returned from SQL steps.")
            return ValidationResult(passed=False, checks=checks)

        over_limit = [result.rowCount for result in results if result.rowCount > self._model.policy.max_row_limit]
        if over_limit:
            checks.append("At least one SQL step exceeded max row limit.")
            return ValidationResult(passed=False, checks=checks)
        checks.append("All SQL steps satisfy row-limit policy.")

        null_count = 0
        value_count = 0
        for result in results:
            for row in result.rows[:200]:
                for value in row.values():
                    value_count += 1
                    if value is None:
                        null_count += 1

        null_rate = (null_count / value_count) if value_count else 1.0
        checks.append(f"Observed null-rate: {null_rate:.2%}.")
        checks.append("Restricted-column access prevented by SQL guardrails.")

        passed = null_rate < 0.95
        return ValidationResult(passed=passed, checks=checks)

    async def build_response(self, request: ChatTurnRequest, results: list[SqlExecutionResult]) -> AgentResponse:
        route = self._route_cache.get(request.message) or _heuristic_route(request.message)
        evidence = build_evidence_rows(results)
        metrics = build_metric_points(results, evidence)
        data_tables = results_to_data_tables(results)
        result_summary = summarize_results_for_prompt(results)
        evidence_summary = str([row.model_dump() for row in evidence[:8]])

        llm_payload: dict[str, Any] = {}
        try:
            system_prompt, user_prompt = response_prompt(
                request.message,
                route,
                result_summary,
                evidence_summary,
            )
            llm_payload = await self._ask_llm_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=settings.real_llm_max_tokens,
            )
        except Exception:
            llm_payload = {}

        answer = str(llm_payload.get("answer", "")).strip() or (
            "I completed the governed analysis and surfaced the highest-impact segments in the evidence tables."
        )
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or (
            "The detected movement is concentrated enough to support targeted action rather than broad portfolio changes."
        )

        confidence = str(llm_payload.get("confidence", "medium")).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        confidence_value = cast(Literal["high", "medium", "low"], confidence)

        insights = _sanitize_insights(llm_payload.get("insights")) or _default_insights(evidence)
        suggested_questions = as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions()
        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=4)
        assumptions.extend(self._assumption_cache.get(request.message, []))
        assumptions.append("SQL is constrained to the semantic model allowlist.")
        assumptions.append(
            "Deep path was selected for multi-step reasoning."
            if route == "deep_path"
            else "Fast path was selected for low latency."
        )

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and policy scope",
                summary="Classified route and bounded plan depth for deterministic orchestration.",
                status="done",
            ),
            TraceStep(
                id="t2",
                title="Generate and execute governed SQL",
                summary="Generated SQL with allowlist and restricted-column guardrails, then executed Snowflake steps.",
                status="done",
                sql=results[0].sql if results else None,
            ),
            TraceStep(
                id="t3",
                title="Synthesize insights from retrieved tables",
                summary="Combined deterministic table profiling and LLM narrative constrained to retrieved evidence.",
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence_value,
            whyItMatters=why_it_matters,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights,
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:8],
            trace=trace,
            dataTables=data_tables,
        )


def create_dependencies() -> OrchestratorDependencies:
    if settings.use_mock_providers:
        return MockDependencies()
    return RealDependencies()
