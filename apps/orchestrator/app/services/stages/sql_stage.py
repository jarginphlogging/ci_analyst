from __future__ import annotations

import asyncio
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _StepSql:
    sql: str
    fallback_sql: str


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

    async def _execute_sql(self, step_sql: _StepSql) -> SqlExecutionResult:
        executed_sql = step_sql.sql
        try:
            raw_rows = await self._sql_fn(executed_sql)
        except Exception:
            executed_sql = step_sql.fallback_sql
            raw_rows = await self._sql_fn(executed_sql)

        normalized_rows = normalize_rows(raw_rows)
        return SqlExecutionResult(
            sql=executed_sql,
            rows=normalized_rows,
            rowCount=len(normalized_rows),
        )

    async def _execute_sql_parallel(self, step_sqls: list[_StepSql]) -> list[SqlExecutionResult]:
        semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))

        async def _run(index: int, step_sql: _StepSql) -> tuple[int, SqlExecutionResult]:
            async with semaphore:
                result = await self._execute_sql(step_sql)
                return index, result

        indexed_results = await asyncio.gather(
            *(_run(index, step_sql) for index, step_sql in enumerate(step_sqls))
        )
        indexed_results.sort(key=lambda item: item[0])
        return [result for _, result in indexed_results]

    async def run_sql(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep],
    ) -> tuple[list[SqlExecutionResult], list[str]]:
        prior_sql: list[str] = []
        accumulated_assumptions: list[str] = []
        step_sqls: list[_StepSql] = []

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
            fallback_sql = guard_sql(
                f"SELECT * FROM {_select_table_for_goal(self._model, step.goal).name}",
                self._model,
            )
            prior_sql.append(guarded_sql)
            step_sqls.append(
                _StepSql(
                    sql=guarded_sql,
                    fallback_sql=fallback_sql,
                )
            )

        if settings.real_enable_parallel_sql and len(step_sqls) > 1:
            results = await self._execute_sql_parallel(step_sqls)
        else:
            results = [await self._execute_sql(step_sql) for step_sql in step_sqls]

        return results, accumulated_assumptions[:6]
