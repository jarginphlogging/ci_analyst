from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Literal, cast

from app.config import settings
from app.models import (
    AgentResponse,
    AnalysisArtifact,
    ChartConfig,
    DataTable,
    EvidenceRow,
    Insight,
    PresentationIntent,
    PrimaryVisual,
    QueryPlanStep,
    SummaryCard,
    SqlExecutionResult,
    SynthesisContextPackage,
    SynthesisExecutedStep,
    SynthesisPlanStep,
    SynthesisPortfolioSummary,
    SynthesisQueryContext,
    SynthesisVisualArtifact,
    TableColumnConfig,
    TableConfig,
    TraceStep,
)
from app.prompts.templates import response_prompt
from app.services.llm_json import as_string_list
from app.services.llm_trace import llm_trace_stage
from app.services.stages.data_summarizer_stage import DataSummarizerStage
from app.services.table_analysis import (
    build_analysis_artifacts,
    build_evidence_rows,
    build_metric_points,
    detect_grain_mismatch,
    results_to_data_tables,
)

AskLlmJsonFn = Callable[..., Awaitable[dict[str, Any]]]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _prettify(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _is_time_value(value: Any) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return True
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _column_kind(table: DataTable, column: str) -> Literal["number", "date", "string"]:
    values = [row.get(column) for row in table.rows[:250] if row.get(column) is not None]
    if not values:
        return "string"
    numeric = sum(1 for value in values if _as_float(value) is not None)
    dates = sum(1 for value in values if _is_time_value(value))
    total = max(1, len(values))
    if numeric / total >= 0.7:
        return "number"
    if dates / total >= 0.7:
        return "date"
    return "string"


def _first_column_by_kind(table: DataTable, kind: Literal["number", "date", "string"], *, exclude: set[str] | None = None) -> str | None:
    blocked = exclude or set()
    for column in table.columns:
        if column in blocked:
            continue
        if _column_kind(table, column) == kind:
            return column
    return None


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
        items.append(Insight(id=f"i{index}", title=title, detail=detail, importance=normalized_importance))
    return items


def _sanitize_summary_cards(raw: Any) -> list[SummaryCard]:
    if not isinstance(raw, list):
        return []
    cards: list[SummaryCard] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw[:3]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        value = str(entry.get("value", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not label or not value:
            continue
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        cards.append(SummaryCard(label=label, value=value, detail=detail))
    return cards


def _normalize_confidence(raw_confidence: str) -> Literal["high", "medium", "low"]:
    confidence = raw_confidence.lower().strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return cast(Literal["high", "medium", "low"], confidence)


def _default_questions(artifacts: list[AnalysisArtifact]) -> list[str]:
    if any(artifact.kind == "ranking_breakdown" for artifact in artifacts):
        return [
            "Can you break the top entities down by channel?",
            "Which entities moved most versus prior period?",
            "What percentage of total comes from the top decile?",
        ]
    if any(artifact.kind == "trend_breakdown" for artifact in artifacts):
        return [
            "Which segments are driving this trend?",
            "How does this compare to the same period last year?",
            "Where are change points or anomalies?",
        ]
    return [
        "Can you break this down by state and channel?",
        "How does this compare to the previous period?",
        "Which segments are driving the result?",
    ]


def _deterministic_answer(results: list[SqlExecutionResult]) -> str:
    if not results:
        return "I completed the governed pipeline but no usable rows were returned."
    total_rows = sum(result.rowCount for result in results)
    return f"I retrieved {total_rows} rows and prepared a governed summary with visual-ready data."


def _deterministic_why_it_matters() -> str:
    return "Insights are grounded in the retrieved SQL output, and visuals are validated before rendering."


def _default_chart_config(intent: PresentationIntent, table: DataTable) -> ChartConfig | None:
    chart_type = intent.chartType or "line"
    x = _first_column_by_kind(table, "date") or (table.columns[0] if table.columns else None)
    if x is None:
        return None
    y = _first_column_by_kind(table, "number", exclude={x})
    if y is None:
        return None
    series = _first_column_by_kind(table, "string", exclude={x, y})
    return ChartConfig(
        type=chart_type,
        x=x,
        y=y,
        series=series,
        xLabel=_prettify(x),
        yLabel=_prettify(y),
        yFormat="currency" if any(token in y.lower() for token in ("sales", "revenue", "amount", "spend", "cost")) else "number",
    )


def _default_table_config(intent: PresentationIntent, table: DataTable) -> TableConfig:
    style = intent.tableStyle or "simple"
    columns = [
        TableColumnConfig(
            key=column,
            label=_prettify(column),
            format=(
                "number"
                if _column_kind(table, column) == "number"
                else "date"
                if _column_kind(table, column) == "date"
                else "string"
            ),
            align="right" if _column_kind(table, column) == "number" else "left",
        )
        for column in table.columns
    ]
    numeric_sort = _first_column_by_kind(table, "number")
    return TableConfig(
        style=style,
        columns=columns,
        sortBy=numeric_sort,
        sortDir="desc" if numeric_sort else None,
        showRank=style == "ranked",
    )


def _sanitize_chart_config(raw: Any, table: DataTable) -> ChartConfig | None:
    if not isinstance(raw, dict):
        return None
    chart_type = str(raw.get("type", "")).strip().lower().replace("-", "_")
    if chart_type not in {"line", "bar", "stacked_bar", "grouped_bar"}:
        return None
    x = str(raw.get("x", "")).strip()
    if x not in table.columns:
        return None
    y_raw = raw.get("y")
    if isinstance(y_raw, list):
        y = [str(item).strip() for item in y_raw if str(item).strip()]
        if not y:
            return None
        if any(column not in table.columns for column in y):
            return None
        y_value: str | list[str] = y
    else:
        y_str = str(y_raw or "").strip()
        if y_str not in table.columns:
            return None
        y_value = y_str
    series = str(raw.get("series", "")).strip() or None
    if series and series not in table.columns:
        return None

    distinct_x = len({row.get(x) for row in table.rows if row.get(x) is not None})
    if distinct_x < 3:
        return None
    if series:
        series_count = len({row.get(series) for row in table.rows if row.get(series) is not None})
        if series_count > 10:
            return None

    y_format = str(raw.get("yFormat", "number")).strip().lower()
    if y_format not in {"currency", "number", "percent"}:
        y_format = "number"
    return ChartConfig(
        type=cast(Literal["line", "bar", "stacked_bar", "grouped_bar"], chart_type),
        x=x,
        y=y_value,
        series=series,
        xLabel=str(raw.get("xLabel", "")).strip() or _prettify(x),
        yLabel=str(raw.get("yLabel", "")).strip() or _prettify(y_value[0] if isinstance(y_value, list) else y_value),
        yFormat=cast(Literal["currency", "number", "percent"], y_format),
    )


def _sanitize_table_config(raw: Any, table: DataTable) -> TableConfig | None:
    if not isinstance(raw, dict):
        return None
    style = str(raw.get("style", "simple")).strip().lower()
    if style not in {"simple", "ranked", "comparison"}:
        style = "simple"

    raw_columns = raw.get("columns")
    columns: list[TableColumnConfig] = []
    if isinstance(raw_columns, list):
        for item in raw_columns:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if key not in table.columns:
                continue
            fmt = str(item.get("format", "string")).strip().lower()
            if fmt not in {"currency", "number", "percent", "date", "string"}:
                fmt = "string"
            align = str(item.get("align", "left")).strip().lower()
            if align not in {"left", "right"}:
                align = "left"
            columns.append(
                TableColumnConfig(
                    key=key,
                    label=str(item.get("label", "")).strip() or _prettify(key),
                    format=cast(Literal["currency", "number", "percent", "date", "string"], fmt),
                    align=cast(Literal["left", "right"], align),
                )
            )
    if not columns:
        return _default_table_config(PresentationIntent(displayType="table", tableStyle=cast(Literal["simple", "ranked", "comparison"], style)), table)

    sort_by = str(raw.get("sortBy", "")).strip() or None
    if sort_by and sort_by not in table.columns:
        sort_by = None
    sort_dir_raw = str(raw.get("sortDir", "")).strip().lower()
    sort_dir = cast(Literal["asc", "desc"], sort_dir_raw) if sort_dir_raw in {"asc", "desc"} else None
    return TableConfig(
        style=cast(Literal["simple", "ranked", "comparison"], style),
        columns=columns,
        sortBy=sort_by,
        sortDir=sort_dir,
        showRank=bool(raw.get("showRank", style == "ranked")),
    )


def _resolve_visual_config(
    *,
    llm_payload: dict[str, Any],
    presentation_intent: PresentationIntent,
    data_tables: list[DataTable],
) -> tuple[ChartConfig | None, TableConfig | None, list[str]]:
    issues: list[str] = []
    primary_table = data_tables[0] if data_tables else None
    if primary_table is None:
        return None, None, ["No data table available for visual configuration."]

    chart_config: ChartConfig | None = None
    table_config: TableConfig | None = None
    if presentation_intent.displayType == "chart":
        chart_config = _sanitize_chart_config(llm_payload.get("chartConfig"), primary_table)
        if chart_config is None:
            fallback_chart = _default_chart_config(presentation_intent, primary_table)
            if fallback_chart is not None:
                chart_config = fallback_chart
                issues.append("Chart config fallback applied from deterministic defaults.")
            else:
                table_config = _sanitize_table_config(llm_payload.get("tableConfig"), primary_table) or _default_table_config(
                    PresentationIntent(displayType="table", tableStyle="simple"), primary_table
                )
                issues.append("Chart unavailable for result shape; downgraded to table.")
    elif presentation_intent.displayType == "table":
        table_config = _sanitize_table_config(llm_payload.get("tableConfig"), primary_table) or _default_table_config(
            presentation_intent, primary_table
        )
    else:
        # Inline intent: do not force a visual unless model provides a valid one.
        chart_config = _sanitize_chart_config(llm_payload.get("chartConfig"), primary_table)
        if chart_config is None:
            table_config = None
    return chart_config, table_config, issues


def _primary_visual_from_config(chart_config: ChartConfig | None, table_config: TableConfig | None) -> PrimaryVisual | None:
    if chart_config is not None:
        visual_type = "trend" if chart_config.type == "line" else "comparison" if chart_config.type == "grouped_bar" else "ranking"
        return PrimaryVisual(
            title=f"{_prettify(chart_config.y[0] if isinstance(chart_config.y, list) else chart_config.y)} by {_prettify(chart_config.x)}",
            description="Validated chart generated from retrieved SQL output.",
            visualType=cast(Literal["trend", "ranking", "comparison", "distribution", "snapshot", "table"], visual_type),
        )
    if table_config is not None:
        return PrimaryVisual(
            title="Primary data table",
            description="Validated table generated from retrieved SQL output.",
            visualType="table",
        )
    return None


class SynthesisStage:
    def __init__(self, *, ask_llm_json: AskLlmJsonFn) -> None:
        self._ask_llm_json = ask_llm_json
        self._data_summarizer = DataSummarizerStage()

    async def build_fast_response(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            plan=plan,
            presentation_intent=presentation_intent,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=False,
        )

    async def build_response(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
    ) -> AgentResponse:
        return await self._build_response(
            message=message,
            route=route,
            plan=plan,
            presentation_intent=presentation_intent,
            results=results,
            prior_assumptions=prior_assumptions,
            history=history,
            with_llm=True,
        )

    def _synthesis_context_package(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        results: list[SqlExecutionResult],
        artifacts: list[AnalysisArtifact],
    ) -> SynthesisContextPackage:
        resolved_route = route.strip() or "unclassified"
        plan_steps = plan or []
        table_summaries = self._data_summarizer.summarize_tables(results=results, message=message)
        synthesis_plan = [
            SynthesisPlanStep(id=step.id, goal=step.goal, dependsOn=step.dependsOn, independent=step.independent)
            for step in plan_steps
        ]
        executed_steps: list[SynthesisExecutedStep] = []
        for index, result in enumerate(results, start=1):
            step = plan_steps[index - 1] if index - 1 < len(plan_steps) else None
            table_summary = table_summaries[index - 1] if index - 1 < len(table_summaries) else {}
            plan_step = (
                SynthesisPlanStep(id=step.id, goal=step.goal, dependsOn=step.dependsOn, independent=step.independent)
                if step
                else SynthesisPlanStep(id=f"step_{index}", goal="No explicit plan step was available.", dependsOn=[], independent=True)
            )
            executed_steps.append(
                SynthesisExecutedStep(
                    stepIndex=index,
                    planStep=plan_step,
                    executedSql=result.sql,
                    rowCount=result.rowCount,
                    tableSummary=table_summary,
                )
            )
        return SynthesisContextPackage(
            queryContext=SynthesisQueryContext(originalUserQuery=message, route=resolved_route),
            plan=synthesis_plan,
            executedSteps=executed_steps,
            availableVisualArtifacts=[
                SynthesisVisualArtifact(kind=artifact.kind, title=artifact.title, rowCount=len(artifact.rows))
                for artifact in artifacts
                if artifact.rows
            ],
            portfolioSummary=SynthesisPortfolioSummary(
                tableCount=len(results),
                totalRows=sum(result.rowCount for result in results),
            ),
        )

    async def _build_response(
        self,
        *,
        message: str,
        route: str,
        plan: list[QueryPlanStep] | None,
        presentation_intent: PresentationIntent,
        results: list[SqlExecutionResult],
        prior_assumptions: list[str],
        history: list[str],
        with_llm: bool,
    ) -> AgentResponse:
        _ = prior_assumptions
        evidence = build_evidence_rows(results, message=message)
        artifacts = build_analysis_artifacts(results, message=message)
        metrics = build_metric_points(results, evidence, message=message)
        data_tables = results_to_data_tables(results)
        synthesis_context = self._synthesis_context_package(
            message=message,
            route=route,
            plan=plan,
            results=results,
            artifacts=artifacts,
        )
        result_summary = synthesis_context.model_dump_json()
        evidence_summary = str([row.model_dump() for row in evidence[:8]])

        llm_payload: dict[str, Any] = {}
        if with_llm:
            try:
                system_prompt, user_prompt = response_prompt(
                    message,
                    route,
                    json.dumps(presentation_intent.model_dump(), ensure_ascii=True),
                    result_summary,
                    evidence_summary,
                    history,
                )
                with llm_trace_stage(
                    "synthesis_final",
                    {"planStepCount": len(plan or []), "historyDepth": len(history)},
                ):
                    llm_payload = await self._ask_llm_json(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        max_tokens=settings.real_llm_max_tokens,
                    )
            except Exception:
                if settings.provider_mode in {"sandbox", "prod"}:
                    raise
                llm_payload = {}

        answer = str(llm_payload.get("answer", "")).strip() or _deterministic_answer(results)
        why_it_matters = str(llm_payload.get("whyItMatters", "")).strip() or _deterministic_why_it_matters()
        confidence_default = "medium" if with_llm else "high"
        confidence = _normalize_confidence(str(llm_payload.get("confidence", confidence_default)))
        confidence_reason = str(llm_payload.get("confidenceReason", "")).strip()
        if not confidence_reason:
            llm_assumptions = as_string_list(llm_payload.get("assumptions"), max_items=1)
            if llm_assumptions:
                confidence_reason = llm_assumptions[0]
        if not confidence_reason:
            confidence_reason = why_it_matters

        chart_config, table_config, _visual_issues = _resolve_visual_config(
            llm_payload=llm_payload,
            presentation_intent=presentation_intent,
            data_tables=data_tables,
        )
        insights = _sanitize_insights(llm_payload.get("insights")) or [
            Insight(id="i1", title="Primary data is ready", detail="Tabular evidence is available for inspection and export.", importance="medium")
        ]
        summary_cards = _sanitize_summary_cards(llm_payload.get("summaryCards"))
        if not summary_cards:
            summary_cards = [
                SummaryCard(label=metric.label, value=f"{metric.value:,.2f}" if metric.unit != "count" else f"{metric.value:,.0f}")
                for metric in metrics[:3]
            ]
        suggested_questions = as_string_list(llm_payload.get("suggestedQuestions"), max_items=3) or _default_questions(artifacts)

        assumptions = as_string_list(llm_payload.get("assumptions"), max_items=5)
        grain_mismatch = detect_grain_mismatch(results, message)
        if grain_mismatch:
            requested, detected = grain_mismatch
            if confidence == "high":
                confidence = "medium"

        trace = [
            TraceStep(
                id="t1",
                title="Resolve intent and presentation path",
                summary="Validated relevance and generated a bounded delegation plan with presentation intent.",
                status="done",
            ),
            TraceStep(
                id="t2",
                title="Generate and execute governed SQL",
                summary="Generated SQL with allowlist and restricted-column guardrails, then executed warehouse steps.",
                status="done",
                sql=results[0].sql if results else None,
            ),
            TraceStep(
                id="t3",
                title="Synthesize narrative and visual config",
                summary=(
                    "Built deterministic narrative and visual fallback from retrieved data."
                    if not with_llm
                    else "Combined deterministic summaries with constrained narrative synthesis and validated visual config."
                ),
                status="done",
            ),
        ]

        return AgentResponse(
            answer=answer,
            confidence=confidence,
            confidenceReason=confidence_reason,
            whyItMatters=why_it_matters,
            presentationIntent=presentation_intent,
            chartConfig=chart_config,
            tableConfig=table_config,
            metrics=metrics[:3],
            evidence=evidence[:10],
            insights=insights[:4],
            suggestedQuestions=suggested_questions,
            assumptions=assumptions[:5],
            trace=trace,
            summaryCards=summary_cards,
            primaryVisual=_primary_visual_from_config(chart_config, table_config),
            dataTables=data_tables,
            artifacts=artifacts,
        )


def build_incremental_answer_deltas(fast_answer: str, final_answer: str) -> list[str]:
    _ = fast_answer
    final = final_answer.strip()
    if not final:
        return [""]
    return [f"{token} " for token in final.split(" ")]
