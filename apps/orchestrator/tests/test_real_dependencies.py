from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import ChatTurnRequest
from app.services.dependencies import RealDependencies
from app.services.semantic_model import load_semantic_model


async def fake_llm(**kwargs) -> str:  # type: ignore[no-untyped-def]
    system_prompt = kwargs.get("system_prompt", "")

    if "routing model" in system_prompt:
        return '{"route":"deep_path","reason":"multi-step decomposition requested"}'

    if "deterministic analytics plans" in system_prompt:
        return (
            '{"steps":['
            '{"goal":"Retrieve fraud loss trend by region","primaryMetric":"fraud_loss_rate","grain":"region","timeWindow":"last quarter"},'
            '{"goal":"Decompose by channel and corridor","primaryMetric":"fraud_loss_rate","grain":"channel","timeWindow":"last quarter"}'
            "]}")

    if "SQL generator" in system_prompt:
        return (
            '{"sql":"SELECT region AS segment, 0.82 AS prior, 1.26 AS current, 44 AS changeBps, 0.61 AS contribution '
            'FROM curated.fraud_summary LIMIT 50",'
            '"assumptions":["latest settled quarter used"]}'
        )

    if "executive analytics narrator" in system_prompt:
        return (
            '{"answer":"Fraud losses increased, concentrated in a few segments.",'
            '"whyItMatters":"Concentration allows targeted controls.",'
            '"confidence":"high",'
            '"insights":[{"title":"Concentration signal","detail":"Top segments account for most of the movement.","importance":"high"}],'
            '"suggestedQuestions":["Which corridors explain most of the increase?","What changed by channel?","Which controls are fastest?"],'
            '"assumptions":["Data reflects settled transactions only."]}'
        )

    return "{}"


async def fake_sql(_: str) -> list[dict[str, float | str]]:
    return [
        {"segment": "NA - CNP", "prior": 0.82, "current": 1.26, "changeBps": 44, "contribution": 0.61},
        {"segment": "EMEA - CNP", "prior": 0.55, "current": 0.68, "changeBps": 13, "contribution": 0.14},
    ]


async def failing_llm(**kwargs) -> str:  # type: ignore[no-untyped-def]
    raise RuntimeError("llm unavailable")


@pytest.mark.asyncio
async def test_real_dependencies_pipeline_with_llm_outputs() -> None:
    request = ChatTurnRequest(sessionId=uuid4(), message="Where are fraud losses accelerating and why?")
    deps = RealDependencies(llm_fn=fake_llm, sql_fn=fake_sql, model=load_semantic_model())

    route = await deps.classify_route(request)
    plan = await deps.create_plan(request)
    results = await deps.run_sql(request, plan)
    validation = await deps.validate_results(results)
    response = await deps.build_response(request, results)

    assert route == "deep_path"
    assert len(plan) >= 1
    assert validation.passed
    assert response.answer
    assert response.dataTables
    assert response.trace
    assert response.metrics


@pytest.mark.asyncio
async def test_real_dependencies_pipeline_fallbacks_without_llm() -> None:
    request = ChatTurnRequest(sessionId=uuid4(), message="Show deposit movement by segment")
    deps = RealDependencies(llm_fn=failing_llm, sql_fn=fake_sql, model=load_semantic_model())

    route = await deps.classify_route(request)
    plan = await deps.create_plan(request)
    results = await deps.run_sql(request, plan)
    validation = await deps.validate_results(results)
    response = await deps.build_response(request, results)

    assert route in {"fast_path", "deep_path"}
    assert len(plan) >= 1
    assert len(results) >= 1
    assert validation.passed
    assert response.answer
    assert response.insights
