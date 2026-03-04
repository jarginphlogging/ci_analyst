from __future__ import annotations

from app.prompts.templates import sql_prompt
from app.services.semantic_model import load_semantic_model
from app.services.semantic_model_yaml import load_semantic_model_yaml


def test_sql_prompt_includes_full_semantic_model_yaml() -> None:
    model = load_semantic_model()
    full_yaml = load_semantic_model_yaml().raw_text.strip()

    _, user_prompt = sql_prompt(
        user_message="Show spend by state for Q4 2025",
        step_id="step_1",
        step_goal="Compute spend totals by state for Q4 2025.",
        model=model,
        prior_sql=[],
        history=[],
    )

    assert "Semantic model (full semantic_model.yaml):" in user_prompt
    assert full_yaml in user_prompt
