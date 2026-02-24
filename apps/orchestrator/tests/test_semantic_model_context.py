from __future__ import annotations

from app.services.semantic_model import load_semantic_model, semantic_model_planner_context


def test_semantic_model_planner_context_is_minimal_and_actionable() -> None:
    model = load_semantic_model()
    context = semantic_model_planner_context(model)

    assert "Planning scope (minimum context):" in context
    assert "In-domain business concepts:" in context
    assert "Time semantics:" in context
    assert "no table or column names" in context
    assert "cia_sales_insights_cortex" not in context
    assert "entities:" not in context
    assert "measures:" not in context
    assert "Semantic model excerpt" not in context
