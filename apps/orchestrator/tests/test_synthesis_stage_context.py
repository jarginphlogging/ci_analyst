from __future__ import annotations

import pytest

from app.models import QueryPlanStep, SqlExecutionResult
from app.services.stages.synthesis_stage import SynthesisStage


@pytest.mark.asyncio
async def test_synthesis_stage_uses_plan_sql_and_table_summary_context() -> None:
    captured_prompts: dict[str, str] = {}

    async def fake_ask_llm_json(**kwargs):  # type: ignore[no-untyped-def]
        captured_prompts["system"] = str(kwargs.get("system_prompt", ""))
        captured_prompts["user"] = str(kwargs.get("user_prompt", ""))
        return {
            "answer": "Synthesis answer",
            "whyItMatters": "Synthesis impact",
            "confidence": "high",
            "insights": [
                {
                    "title": "Top movement",
                    "detail": "TX has the largest movement.",
                    "importance": "high",
                }
            ],
            "suggestedQuestions": ["Q1", "Q2", "Q3"],
            "assumptions": ["A1"],
        }

    stage = SynthesisStage(ask_llm_json=fake_ask_llm_json)
    plan = [
        QueryPlanStep(
            id="step_1",
            goal="Compute spend and transaction trend by state for Q4 2025.",
            dependsOn=[],
            independent=True,
        )
    ]
    results = [
        SqlExecutionResult(
            sql=(
                "SELECT transaction_state, current_value, prior_value, change_value "
                "FROM cia_sales_insights_cortex"
            ),
            rows=[
                {
                    "transaction_state": "TX",
                    "current_value": 120.0,
                    "prior_value": 100.0,
                    "change_value": 20.0,
                },
                {
                    "transaction_state": "FL",
                    "current_value": 90.0,
                    "prior_value": 110.0,
                    "change_value": -20.0,
                },
            ],
            rowCount=2,
        )
    ]

    response = await stage.build_response(
        message="Compare Q4 2025 performance by state.",
        route="deep_path",
        plan=plan,
        results=results,
        prior_assumptions=[],
        history=[],
    )

    assert response.answer == "Synthesis answer"
    prompt_text = captured_prompts["user"]
    assert '"originalUserQuery":"Compare Q4 2025 performance by state."' in prompt_text
    assert '"plan":[{"id":"step_1","goal":"Compute spend and transaction trend by state for Q4 2025."' in prompt_text
    assert '"executedSql":"SELECT transaction_state, current_value, prior_value, change_value FROM cia_sales_insights_cortex"' in prompt_text
    assert '"tableSummary":' in prompt_text
    assert '"numericStats"' in prompt_text
