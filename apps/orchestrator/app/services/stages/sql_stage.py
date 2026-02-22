from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.models import QueryPlanStep, SqlExecutionResult
from app.prompts.templates import sql_prompt
from app.services.llm_json import as_string_list
from app.services.semantic_model import SemanticModel, SemanticTable
from app.services.sql_guardrails import guard_sql
from app.services.table_analysis import normalize_rows

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
ProgressFn = Callable[[str], Optional[Awaitable[None]]]


@dataclass(frozen=True)
class _StepSql:
    sql: str
    fallback_sql: str


async def _emit_progress(progress_callback: ProgressFn | None, message: str) -> None:
    if progress_callback is None:
        return
    maybe_result = progress_callback(message)
    if inspect.isawaitable(maybe_result):
        await maybe_result


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


def _infer_requested_grain(message: str) -> str | None:
    query = message.lower()
    if any(token in query for token in ["store", "stores", "branch", "branches", "td_id", "location"]):
        return "store"
    if any(token in query for token in ["channel", "card present", "card not present", "cnp", "cp"]):
        return "channel"
    if any(token in query for token in ["state", "states"]):
        return "state"
    if any(token in query for token in ["trend", "month", "weekly", "quarter", "year", "yoy", "mom"]):
        return "time"
    return None


def _is_period_comparison_intent(message: str) -> bool:
    text = message.lower()
    return any(
        token in text
        for token in ["compare", "compared", "versus", "vs", "yoy", "year-over-year", "same period last year"]
    )


def _detect_result_grain(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    lowered = [column.lower() for column in rows[0].keys()]
    if any(re.search(r"(td_id|store|branch|location)", column) for column in lowered):
        return "store"
    if any(re.search(r"(transaction_state|_state$|^state$)", column) for column in lowered):
        return "state"
    if any(re.search(r"(channel|card_present|card_not_present)", column) for column in lowered):
        return "channel"
    if any(re.search(r"(resp_date|date|month|week|quarter|year)", column) for column in lowered):
        return "time"
    return None


def _has_period_context(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False

    columns = [column.lower() for column in rows[0].keys()]
    if any(re.search(r"(data_from|data_through|max_dt|min_dt|resp_date|date|month|week|quarter|year)", column) for column in columns):
        return True

    for row in rows[:20]:
        for value in row.values():
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text:
                continue
            if re.match(r"^\d{4}-\d{1,2}-\d{1,2}", text):
                return True
    return False


def _has_period_comparison_shape(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    columns = [column.lower() for column in rows[0].keys()]
    has_change = any(re.search(r"(change|delta|yoy|mom|variance|diff)", column) for column in columns)
    has_current = any(re.search(r"(current|latest|this)", column) for column in columns)
    has_prior = any(re.search(r"(prior|previous|prev|baseline|last)", column) for column in columns)

    year_columns = [column for column in columns if re.search(r"20\d{2}", column)]
    has_year_pair = len(year_columns) >= 2

    return has_change or (has_current and has_prior) or has_year_pair


def _primary_result_index(results: list[SqlExecutionResult]) -> int:
    if not results:
        return 0

    best_index = 0
    best_score = float("-inf")
    for index, result in enumerate(results):
        if not result.rows:
            continue
        columns = len(result.rows[0])
        score = (result.rowCount * 4.0) + columns
        if result.rowCount <= 1:
            score -= 4.0
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _metric_clauses_for_message(message: str, table: SemanticTable) -> list[tuple[str, str]]:
    text = message.lower()
    metrics = {metric.lower() for metric in table.metrics}

    def has(metric: str) -> bool:
        return metric in metrics

    clauses: list[tuple[str, str]] = []

    if any(token in text for token in ["sales", "spend", "revenue", "amount"]) and has("spend"):
        clauses.append(("SUM(spend)", "total_spend"))
    if any(token in text for token in ["transaction", "transactions", "volume", "count"]) and has("transactions"):
        clauses.append(("SUM(transactions)", "total_transactions"))
    if any(token in text for token in ["average", "avg", "ticket", "sale amount"]) and has("spend") and has("transactions"):
        clauses.append(("SUM(spend) / NULLIF(SUM(transactions), 0)", "avg_sale_amount"))

    if "repeat" in text:
        if has("repeat_spend"):
            clauses.append(("SUM(repeat_spend)", "repeat_spend"))
        if has("repeat_transactions"):
            clauses.append(("SUM(repeat_transactions)", "repeat_transactions"))
    if "new" in text:
        if has("new_spend"):
            clauses.append(("SUM(new_spend)", "new_spend"))
        if has("new_transactions"):
            clauses.append(("SUM(new_transactions)", "new_transactions"))

    if any(token in text for token in ["card present", " cp", "channel cp"]) and has("cp_spend"):
        clauses.append(("SUM(cp_spend)", "cp_spend"))
    if any(token in text for token in ["card not present", "cnp"]) and has("cnp_spend"):
        clauses.append(("SUM(cnp_spend)", "cnp_spend"))

    if not clauses:
        if has("spend"):
            clauses.append(("SUM(spend)", "total_spend"))
        elif has("transactions"):
            clauses.append(("SUM(transactions)", "total_transactions"))
        elif table.metrics:
            default_metric = table.metrics[0]
            clauses.append((f"SUM({default_metric})", f"total_{default_metric}"))

    seen_alias: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for expr, alias in clauses:
        if alias in seen_alias:
            continue
        seen_alias.add(alias)
        deduped.append((expr, alias))

    return deduped


def _where_clause_for_message(message: str, table: SemanticTable) -> str | None:
    dimensions = {dimension.lower() for dimension in table.dimensions}
    if "resp_date" not in dimensions:
        return None

    text = message.lower()
    year_match = re.search(r"\b(20\d{2})\b", text)
    quarter_match = re.search(r"\bq([1-4])\b", text)

    if year_match and quarter_match:
        year = int(year_match.group(1))
        quarter = int(quarter_match.group(1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        return (
            "WHERE resp_date BETWEEN "
            f"'{year:04d}-{start_month:02d}-01' AND LAST_DAY('{year:04d}-{end_month:02d}-01')"
        )

    if year_match:
        year = int(year_match.group(1))
        return f"WHERE YEAR(resp_date) = {year}"

    if "last month" in text:
        return "WHERE resp_date >= DATEADD(month, -1, DATE_TRUNC('month', CURRENT_DATE()))"

    return None


def _contract_sql_for_message(model: SemanticModel, message: str, required_grain: str) -> str | None:
    table = _first_table(model)
    dimensions = {dimension.lower(): dimension for dimension in table.dimensions}

    grain_dimensions: dict[str, list[str]] = {
        "store": ["td_id", "transaction_city", "transaction_state"],
        "state": ["transaction_state"],
        "channel": ["channel"],
        "time": ["resp_date"],
    }

    requested_dims = [dimensions[name] for name in grain_dimensions.get(required_grain, []) if name in dimensions]
    if not requested_dims:
        return None

    metric_clauses = _metric_clauses_for_message(message, table)
    if not metric_clauses:
        return None

    select_clauses = [*requested_dims, *[f"{expr} AS {alias}" for expr, alias in metric_clauses]]

    if required_grain != "time" and "resp_date" in dimensions:
        select_clauses.append("MIN(resp_date) AS data_from")
        select_clauses.append("MAX(resp_date) AS data_through")

    sql_lines = [f"SELECT {', '.join(select_clauses)}", f"FROM {table.name}"]
    where_clause = _where_clause_for_message(message, table)
    if where_clause:
        sql_lines.append(where_clause)

    sql_lines.append(f"GROUP BY {', '.join(requested_dims)}")
    order_alias = metric_clauses[0][1]
    order_direction = "ASC" if required_grain == "time" else "DESC"
    sql_lines.append(f"ORDER BY {order_alias} {order_direction}")
    return "\n".join(sql_lines)


def _comparison_period_from_message(message: str) -> tuple[int, int] | None:
    text = message.lower()
    quarter_match = re.search(r"\bq([1-4])\b", text)
    year_matches = [int(value) for value in re.findall(r"\b(20\d{2})\b", text)]
    if not quarter_match or not year_matches:
        return None

    quarter = int(quarter_match.group(1))
    current_year = max(year_matches)
    return quarter, current_year


def _build_period_comparison_sql(model: SemanticModel, message: str) -> str | None:
    period = _comparison_period_from_message(message)
    if period is None:
        return None

    quarter, current_year = period
    prior_year = current_year - 1
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2

    table = _first_table(model)
    dimensions = {dimension.lower() for dimension in table.dimensions}
    metrics = {metric.lower() for metric in table.metrics}
    if "resp_date" not in dimensions or "spend" not in metrics or "transactions" not in metrics:
        return None

    current_start = f"{current_year:04d}-{start_month:02d}-01"
    current_end = f"{current_year:04d}-{end_month:02d}-31"
    prior_start = f"{prior_year:04d}-{start_month:02d}-01"
    prior_end = f"{prior_year:04d}-{end_month:02d}-31"

    return f"""
WITH scoped AS (
  SELECT
    CASE
      WHEN resp_date BETWEEN '{current_start}' AND '{current_end}' THEN 'current'
      WHEN resp_date BETWEEN '{prior_start}' AND '{prior_end}' THEN 'prior'
      ELSE NULL
    END AS period,
    spend,
    transactions
  FROM {table.name}
  WHERE resp_date BETWEEN '{prior_start}' AND '{current_end}'
),
agg AS (
  SELECT
    period,
    SUM(spend) AS total_sales,
    SUM(transactions) AS total_transactions,
    SUM(spend) / NULLIF(SUM(transactions), 0) AS avg_sale_amount
  FROM scoped
  WHERE period IS NOT NULL
  GROUP BY period
),
metric_pairs AS (
  SELECT
    'sales' AS metric,
    MAX(CASE WHEN period = 'current' THEN total_sales END) AS current_value,
    MAX(CASE WHEN period = 'prior' THEN total_sales END) AS prior_value
  FROM agg
  UNION ALL
  SELECT
    'transactions' AS metric,
    MAX(CASE WHEN period = 'current' THEN total_transactions END) AS current_value,
    MAX(CASE WHEN period = 'prior' THEN total_transactions END) AS prior_value
  FROM agg
  UNION ALL
  SELECT
    'avg_sale_amount' AS metric,
    MAX(CASE WHEN period = 'current' THEN avg_sale_amount END) AS current_value,
    MAX(CASE WHEN period = 'prior' THEN avg_sale_amount END) AS prior_value
  FROM agg
)
SELECT
  metric,
  current_value,
  prior_value,
  current_value - prior_value AS change_value,
  CASE
    WHEN prior_value IS NULL OR prior_value = 0 THEN NULL
    ELSE ((current_value - prior_value) / prior_value) * 100
  END AS change_pct
FROM metric_pairs
ORDER BY metric
""".strip()


class SqlExecutionStage:
    def __init__(
        self,
        *,
        model: SemanticModel,
        ask_llm_json: AskLlmJsonFn,
        sql_fn: SqlFn,
        analyst_fn: AnalystFn | None = None,
    ) -> None:
        self._model = model
        self._ask_llm_json = ask_llm_json
        self._sql_fn = sql_fn
        self._analyst_fn = analyst_fn

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

    async def _execute_sql_parallel(
        self,
        step_sqls: list[_StepSql],
        *,
        progress_callback: ProgressFn | None = None,
    ) -> list[SqlExecutionResult]:
        semaphore = asyncio.Semaphore(max(1, settings.real_max_parallel_queries))
        total = len(step_sqls)

        async def _run(index: int, step_sql: _StepSql) -> tuple[int, SqlExecutionResult]:
            async with semaphore:
                await _emit_progress(progress_callback, f"Running SQL step {index + 1}/{total}")
                result = await self._execute_sql(step_sql)
                await _emit_progress(
                    progress_callback,
                    f"Completed SQL step {index + 1}/{total} ({result.rowCount} rows)",
                )
                return index, result

        indexed_results = await asyncio.gather(*(_run(index, step_sql) for index, step_sql in enumerate(step_sqls)))
        indexed_results.sort(key=lambda item: item[0])
        return [result for _, result in indexed_results]

    async def _repair_primary_result_if_needed(
        self,
        *,
        message: str,
        results: list[SqlExecutionResult],
        assumptions: list[str],
        progress_callback: ProgressFn | None = None,
    ) -> None:
        if not results:
            return

        target_index = _primary_result_index(results)
        target_result = results[target_index]
        required_grain = _infer_requested_grain(message)
        detected_grain = _detect_result_grain(target_result.rows)

        if _is_period_comparison_intent(message) and not _has_period_comparison_shape(target_result.rows):
            repair_sql = _build_period_comparison_sql(self._model, message)
            if repair_sql:
                await _emit_progress(progress_callback, "Detected missing period comparison shape; attempting deterministic repair")
                try:
                    guarded_sql = guard_sql(repair_sql, self._model)
                    repaired_rows = normalize_rows(await self._sql_fn(guarded_sql))
                except Exception:
                    repaired_rows = []
                if repaired_rows:
                    results[target_index] = SqlExecutionResult(
                        sql=guarded_sql,
                        rows=repaired_rows,
                        rowCount=len(repaired_rows),
                    )
                    assumptions.append("Auto-repaired SQL output to enforce period-over-period comparison contract.")
                    await _emit_progress(
                        progress_callback,
                        f"Period-comparison repair completed ({len(repaired_rows)} rows)",
                    )
                    target_result = results[target_index]
                    detected_grain = _detect_result_grain(target_result.rows)

        if not _has_period_context(target_result.rows):
            period_grain = required_grain or detected_grain
            if period_grain:
                period_sql = _contract_sql_for_message(self._model, message, period_grain)
                if period_sql:
                    await _emit_progress(progress_callback, "Period context missing; applying deterministic period-context repair")
                    try:
                        guarded_sql = guard_sql(period_sql, self._model)
                        repaired_rows = normalize_rows(await self._sql_fn(guarded_sql))
                    except Exception:
                        repaired_rows = []

                    if repaired_rows and _has_period_context(repaired_rows):
                        results[target_index] = SqlExecutionResult(
                            sql=guarded_sql,
                            rows=repaired_rows,
                            rowCount=len(repaired_rows),
                        )
                        assumptions.append("Auto-repaired SQL output to enforce required period context.")
                        await _emit_progress(
                            progress_callback,
                            f"Period-context repair completed ({len(repaired_rows)} rows)",
                        )
                        target_result = results[target_index]
                        detected_grain = _detect_result_grain(target_result.rows)

        if not required_grain:
            return

        if not detected_grain or detected_grain == required_grain:
            return

        repair_sql = _contract_sql_for_message(self._model, message, required_grain)
        if not repair_sql:
            return

        try:
            guarded_sql = guard_sql(repair_sql, self._model)
            repaired_rows = normalize_rows(await self._sql_fn(guarded_sql))
            repaired_grain = _detect_result_grain(repaired_rows)
        except Exception:
            return

        if not repaired_rows or repaired_grain != required_grain:
            return

        results[target_index] = SqlExecutionResult(
            sql=guarded_sql,
            rows=repaired_rows,
            rowCount=len(repaired_rows),
        )
        assumptions.append(
            f"Auto-repaired SQL output from {detected_grain}-level to requested {required_grain}-level grain."
        )
        await _emit_progress(
            progress_callback,
            f"Grain repair completed ({required_grain}-level, {len(repaired_rows)} rows)",
        )

    async def run_sql(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep],
        history: list[str],
        conversation_id: str = "anonymous",
        progress_callback: ProgressFn | None = None,
    ) -> tuple[list[SqlExecutionResult], list[str]]:
        prior_sql: list[str] = []
        accumulated_assumptions: list[str] = []
        step_sqls: list[_StepSql] = []
        results: list[SqlExecutionResult] = []
        total_steps = len(plan)

        for index, step in enumerate(plan, start=1):
            await _emit_progress(progress_callback, f"Preparing SQL step {index}/{total_steps}: {step.goal}")
            handled_by_analyst = False
            if self._analyst_fn is not None:
                try:
                    await _emit_progress(progress_callback, f"Generating SQL with analyst service for step {index}/{total_steps}")
                    analyst_payload = await self._analyst_fn(
                        conversation_id=conversation_id,
                        message=f"{message}\n\nStep goal: {step.goal}",
                        history=history,
                        route=route,
                        step_id=step.id,
                    )
                    analyst_sql = str(analyst_payload.get("sql", "")).strip()
                    if analyst_sql:
                        guarded_sql = guard_sql(analyst_sql, self._model)
                        prior_sql.append(guarded_sql)

                        payload_rows = analyst_payload.get("rows")
                        if isinstance(payload_rows, list):
                            normalized_rows = normalize_rows(payload_rows)
                        else:
                            normalized_rows = normalize_rows(await self._sql_fn(guarded_sql))

                        clarification = str(analyst_payload.get("clarificationQuestion", "")).strip()
                        if clarification:
                            accumulated_assumptions.append(f"Clarification requested: {clarification}")
                        accumulated_assumptions.extend(as_string_list(analyst_payload.get("assumptions"), max_items=3))
                        results.append(
                            SqlExecutionResult(
                                sql=guarded_sql,
                                rows=normalized_rows,
                                rowCount=len(normalized_rows),
                            )
                        )
                        await _emit_progress(
                            progress_callback,
                            f"Completed SQL step {index}/{total_steps} ({len(normalized_rows)} rows)",
                        )
                        handled_by_analyst = True
                except Exception:
                    pass
            if handled_by_analyst:
                continue

            sql_text = _fallback_sql(self._model, step.goal)
            try:
                await _emit_progress(progress_callback, f"Drafting governed SQL for step {index}/{total_steps}")
                system_prompt, user_prompt = sql_prompt(
                    message,
                    route,
                    step.id,
                    step.goal,
                    self._model,
                    prior_sql,
                    history,
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
            step_sql = _StepSql(
                sql=guarded_sql,
                fallback_sql=fallback_sql,
            )
            if self._analyst_fn is not None:
                await _emit_progress(progress_callback, f"Running SQL step {index}/{total_steps}")
                results.append(await self._execute_sql(step_sql))
                await _emit_progress(
                    progress_callback,
                    f"Completed SQL step {index}/{total_steps} ({results[-1].rowCount} rows)",
                )
            else:
                step_sqls.append(step_sql)

        if self._analyst_fn is None:
            if settings.real_enable_parallel_sql and len(step_sqls) > 1:
                results = await self._execute_sql_parallel(step_sqls, progress_callback=progress_callback)
            else:
                results = []
                for index, step_sql in enumerate(step_sqls, start=1):
                    await _emit_progress(progress_callback, f"Running SQL step {index}/{len(step_sqls)}")
                    result = await self._execute_sql(step_sql)
                    results.append(result)
                    await _emit_progress(
                        progress_callback,
                        f"Completed SQL step {index}/{len(step_sqls)} ({result.rowCount} rows)",
                    )

        await self._repair_primary_result_if_needed(
            message=message,
            results=results,
            assumptions=accumulated_assumptions,
            progress_callback=progress_callback,
        )

        return results, accumulated_assumptions[:6]
