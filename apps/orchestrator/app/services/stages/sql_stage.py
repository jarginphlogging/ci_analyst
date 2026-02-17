from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.config import settings
from app.models import QueryPlanStep, SqlExecutionResult
from app.prompts.templates import sql_prompt
from app.services.llm_json import as_string_list
from app.services.semantic_model import SemanticModel, SemanticTable
from app.services.sql_guardrails import guard_sql
from app.services.table_analysis import normalize_rows

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]


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


class SqlExecutionStage:
    def __init__(
        self,
        *,
        model: SemanticModel,
        ask_llm_json: AskLlmJsonFn,
        sql_fn: SqlFn,
    ) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._sql_fn = sql_fn

    async def run_sql(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep],
    ) -> tuple[list[SqlExecutionResult], list[str]]:
        prior_sql: list[str] = []
        accumulated_assumptions: list[str] = []
        results: list[SqlExecutionResult] = []

        for step in plan:
            sql_text = _fallback_sql(self._model, step.goal)
            try:
                system_prompt, user_prompt = sql_prompt(
                    message,
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

        return results, accumulated_assumptions[:6]
