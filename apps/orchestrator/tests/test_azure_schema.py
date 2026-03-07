from __future__ import annotations

from typing import Any

from app.providers.azure_schema import compile_azure_strict_schema
from app.services.llm_schemas import PlannerResponsePayload, SqlGenerationResponsePayload, SynthesisResponsePayload

_UNSUPPORTED_SCHEMA_KEYS = {
    "const",
    "default",
    "format",
    "maxContains",
    "maxItems",
    "maxLength",
    "maxProperties",
    "maximum",
    "minContains",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "multipleOf",
    "pattern",
    "patternProperties",
    "propertyNames",
    "title",
    "unevaluatedItems",
    "unevaluatedProperties",
    "uniqueItems",
}


def _assert_azure_strict_schema(node: dict[str, Any], *, path: str = "root") -> None:
    unsupported = sorted(_UNSUPPORTED_SCHEMA_KEYS.intersection(node.keys()))
    assert not unsupported, f"{path} contains unsupported keys: {unsupported}"

    properties = node.get("properties")
    if isinstance(properties, dict):
        assert node.get("additionalProperties") is False, f"{path} must set additionalProperties=false"
        assert node.get("required") == list(properties.keys()), f"{path} must require every property"
        for key, value in properties.items():
            assert isinstance(value, dict), f"{path}.properties.{key} must be a schema object"
            _assert_azure_strict_schema(value, path=f"{path}.properties.{key}")

    items = node.get("items")
    if isinstance(items, dict):
        _assert_azure_strict_schema(items, path=f"{path}.items")

    any_of = node.get("anyOf")
    if isinstance(any_of, list):
        for index, value in enumerate(any_of):
            assert isinstance(value, dict), f"{path}.anyOf[{index}] must be a schema object"
            _assert_azure_strict_schema(value, path=f"{path}.anyOf[{index}]")

    defs = node.get("$defs")
    if isinstance(defs, dict):
        for key, value in defs.items():
            assert isinstance(value, dict), f"{path}.$defs.{key} must be a schema object"
            _assert_azure_strict_schema(value, path=f"{path}.$defs.{key}")


def test_compile_azure_strict_schema_preserves_input_schema() -> None:
    original = PlannerResponsePayload.model_json_schema()
    snapshot = PlannerResponsePayload.model_json_schema()

    _ = compile_azure_strict_schema(original)

    assert original == snapshot


def test_compile_azure_strict_schema_for_planner_payload() -> None:
    compiled = compile_azure_strict_schema(PlannerResponsePayload.model_json_schema())

    assert compiled["required"] == [
        "relevance",
        "relevanceReason",
        "presentationIntent",
        "tooComplex",
        "temporalScope",
        "tasks",
    ]
    _assert_azure_strict_schema(compiled)


def test_compile_azure_strict_schema_for_sql_generation_payload() -> None:
    compiled = compile_azure_strict_schema(SqlGenerationResponsePayload.model_json_schema())

    assert compiled["required"] == [
        "generationType",
        "sql",
        "rationale",
        "interpretationNotes",
        "caveats",
        "clarificationQuestion",
        "clarificationKind",
        "notRelevantReason",
        "assumptions",
    ]
    _assert_azure_strict_schema(compiled)


def test_compile_azure_strict_schema_for_synthesis_payload() -> None:
    compiled = compile_azure_strict_schema(SynthesisResponsePayload.model_json_schema())

    assert compiled["required"] == [
        "answer",
        "whyItMatters",
        "confidence",
        "confidenceReason",
        "summaryCards",
        "chartConfig",
        "tableConfig",
        "insights",
        "suggestedQuestions",
        "assumptions",
    ]
    _assert_azure_strict_schema(compiled)
