from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.dependencies import RealDependencies
from app.services.semantic_model import load_semantic_model
from app.services.stages import PlannerBlockedError, SqlGenerationBlockedError


async def fake_llm(**kwargs) -> str:  # type: ignore[no-untyped-def]
    system_prompt = kwargs.get("system_prompt", "")

    if "Customer Insights analytics" in system_prompt and "Return strict JSON only." in system_prompt:
        return (
            '{"relevance":"in_domain","relevanceReason":"Customer insights metrics and segments were requested.",'
            '"analysisType":"comparison","secondaryAnalysisType":"composition_breakdown","tooComplex":false,'
            '"tasks":['
            '{"task":"Retrieve spend and transactions trend by state for the requested time window."},'
            '{"task":"Decompose results by card-present versus card-not-present channel for the same window."}'
            "]}"
        )

    if "SQL generator" in system_prompt:
        return (
            '{"generationType":"sql_ready",'
            '"sql":"SELECT transaction_state, SUM(spend) AS current_value, SUM(transactions) AS prior_value '
            'FROM cia_sales_insights_cortex GROUP BY transaction_state LIMIT 50",'
            '"assumptions":["latest settled quarter used"]}'
        )

    if "executive analytics narrator" in system_prompt:
        return (
            '{"answer":"Spend increased with concentration in a few states and channel mix shifting toward CNP.",'
            '"whyItMatters":"State and channel concentration creates targeted optimization opportunities.",'
            '"confidence":"high",'
            '"confidenceReason":"High confidence because comparison and composition outputs are complete and consistent.",'
            '"summaryCards":[{"label":"Current Spend","value":"$1.94","detail":"Sample value from test pipeline"},{"label":"Prior Spend","value":"$1.37"}],'
            '"primaryVisual":{"title":"Comparison by State","description":"Primary view for comparison intent.","artifactKind":"comparison_breakdown"},'
            '"insights":[{"title":"Concentration signal","detail":"Top states account for most of the movement.","importance":"high"}],'
            '"suggestedQuestions":["Which states drove the increase?","What changed by channel?","How much came from repeat customers?"],'
            '"assumptions":["Data reflects settled transactions only."]}'
        )

    return "{}"


async def fake_sql(_: str) -> list[dict[str, float | str]]:
    return [
        {"segment": "NA - CNP", "prior": 0.82, "current": 1.26, "changeBps": 44, "contribution": 0.61},
        {"segment": "EMEA - CNP", "prior": 0.55, "current": 0.68, "changeBps": 13, "contribution": 0.14},
    ]


async def failing_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
    raise RuntimeError("analyst unavailable")


async def failing_llm(**kwargs) -> str:  # type: ignore[no-untyped-def]
    raise RuntimeError("llm unavailable")


@pytest.mark.asyncio
async def test_real_dependencies_pipeline_with_llm_outputs() -> None:
    request = ChatTurnRequest(sessionId=uuid4(), message="What were my sales by state and how did channel mix change?")
    deps = RealDependencies(llm_fn=fake_llm, sql_fn=fake_sql, analyst_fn=failing_analyst, model=load_semantic_model())

    context = await deps.create_plan(request, [])
    results = await deps.run_sql(request, context, [])
    validation = await deps.validate_results(results)
    response = await deps.build_response(request, context, results, [])

    assert context.route == "standard"
    assert context.analysis_type == "comparison"
    assert context.secondary_analysis_type == "composition_breakdown"
    assert len(context.plan) >= 1
    assert validation.passed
    assert response.answer
    assert response.summaryCards
    assert response.primaryVisual is not None
    assert response.dataTables
    assert response.trace
    assert response.metrics


@pytest.mark.asyncio
async def test_real_dependencies_requires_sql_generation_provider_when_analyst_is_unavailable() -> None:
    request = ChatTurnRequest(sessionId=uuid4(), message="Show transaction trends by state")
    deps = RealDependencies(
        llm_fn=failing_llm,
        sql_fn=fake_sql,
        analyst_fn=failing_analyst,
        model=load_semantic_model(),
    )

    context = await deps.create_plan(request, [])
    with pytest.raises(SqlGenerationBlockedError) as blocked:
        await deps.run_sql(request, context, [])

    assert context.route == "standard"
    assert len(context.plan) >= 1
    assert blocked.value.stop_reason == "technical_failure"


@pytest.mark.asyncio
async def test_real_dependencies_blocks_out_of_domain_request() -> None:
    async def out_of_domain_llm(**kwargs) -> str:  # type: ignore[no-untyped-def]
        system_prompt = kwargs.get("system_prompt", "")
        if "Customer Insights analytics" in system_prompt and "Return strict JSON only." in system_prompt:
            return (
                '{"relevance":"out_of_domain","relevanceReason":"No semantic model entities are relevant.",'
                '"analysisType":"aggregation_summary_stats","tooComplex":false,"tasks":[]}'
            )
        return "{}"

    request = ChatTurnRequest(sessionId=uuid4(), message="What is the weather today?")
    deps = RealDependencies(
        llm_fn=out_of_domain_llm,
        sql_fn=fake_sql,
        analyst_fn=failing_analyst,
        model=load_semantic_model(),
    )

    with pytest.raises(PlannerBlockedError) as blocked:
        await deps.create_plan(request, [])

    assert blocked.value.stop_reason == "out_of_domain"
    assert "Customer Insights" in blocked.value.user_message
