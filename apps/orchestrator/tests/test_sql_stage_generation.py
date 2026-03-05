from __future__ import annotations

import pytest

from app.config import settings
from app.models import QueryPlanStep
from app.services.semantic_model import load_semantic_model
from app.services.stages.sql_stage_generation import SqlStepGenerator


@pytest.mark.asyncio
async def test_sql_step_generator_falls_back_to_llm_when_sandbox_analyst_fails() -> None:
    model = load_semantic_model()

    async def fake_ask_llm_json(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "generationType": "sql_ready",
            "sql": "SELECT transaction_state, SUM(spend) AS total_spend FROM cia_sales_insights_cortex GROUP BY transaction_state",
            "assumptions": ["LLM fallback path used"],
        }

    async def failing_analyst(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = kwargs
        raise RuntimeError("sandbox analyst unavailable")

    generator = SqlStepGenerator(model=model, ask_llm_json=fake_ask_llm_json, analyst_fn=failing_analyst)
    step = QueryPlanStep(id="step-1", goal="Show spend by state")

    original_provider_mode_raw = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "sandbox")
        generated = await generator.generate(
            index=0,
            message="Show spend by state",
            step=step,
            history=[],
            prior_sql=[],
            conversation_id="conv-1",
            attempt_number=1,
        )
    finally:
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode_raw)

    assert generated.provider == "llm"
    assert generated.status == "sql_ready"
    assert generated.sql is not None
    assert "Sandbox analyst provider unavailable" in " ".join(generated.assumptions)
    assert isinstance(generated.generation_error_detail, dict)
