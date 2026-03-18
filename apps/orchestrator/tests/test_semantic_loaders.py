from __future__ import annotations

from app.services.semantic_model import load_semantic_model
from app.services.semantic_model_source import load_semantic_model_source
from app.services.semantic_policy import load_semantic_policy


def test_load_semantic_model_source_reads_yaml_text() -> None:
    source = load_semantic_model_source()

    assert source.path.name == "semantic_model.yaml"
    assert "cia_sales_insights_cortex" in source.raw_text


def test_load_semantic_model_uses_yaml_source() -> None:
    model = load_semantic_model()

    assert model.name == "customer_insights_model"
    assert [table.name for table in model.tables] == ["cia_sales_insights_cortex"]
    assert "resp_date" in model.tables[0].dimensions
    assert "spend" in model.tables[0].metrics


def test_load_semantic_policy_uses_separate_guardrails_config() -> None:
    policy = load_semantic_policy()

    assert policy.allowlisted_tables == ("cia_sales_insights_cortex",)
    assert "customer_id" in policy.restricted_columns
    assert policy.default_row_limit == 1000
    assert policy.max_row_limit == 5000
