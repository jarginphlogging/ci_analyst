from __future__ import annotations

from app.services.semantic_model_source import load_semantic_model_source
from app.prompts.templates import sql_prompt


def test_sql_prompt_includes_full_semantic_model_source_text() -> None:
    full_yaml = load_semantic_model_source().raw_text.strip()

    _, user_prompt = sql_prompt(
        user_message="Show spend by state for Q4 2025",
        step_id="step_1",
        step_goal="Compute spend totals by state for Q4 2025.",
        prior_sql=[],
        history=[],
    )

    assert "Semantic model (full semantic_model.yaml):" in user_prompt
    assert full_yaml in user_prompt


def test_sql_prompt_includes_dependency_context_block() -> None:
    _, user_prompt = sql_prompt(
        user_message="Top and bottom stores with mix",
        step_id="step_2",
        step_goal="Show new vs repeat mix for those stores.",
        prior_sql=["SELECT td_id FROM cia_sales_insights_cortex LIMIT 10"],
        history=[],
        dependency_context=[
            {
                "stepId": "step_1",
                "rowCount": 2,
                "columns": ["td_id"],
                "sampleRows": [{"td_id": "6182655"}],
                "sampleTruncated": False,
            }
        ],
    )

    assert "Dependency context from completed prerequisite steps:" in user_prompt
    assert "\"stepId\": \"step_1\"" in user_prompt


def test_sql_prompt_includes_temporal_scope_contract_block() -> None:
    _, user_prompt = sql_prompt(
        user_message="Show new vs repeat customers by month for the last 6 months",
        step_id="step_1",
        step_goal="Show new vs repeat customers by month for the last 6 months.",
        prior_sql=[],
        history=[],
        temporal_scope={"unit": "month", "count": 6, "granularity": "month"},
    )

    assert "Planner temporal scope contract (hard constraint):" in user_prompt
    assert "\"count\": 6" in user_prompt
