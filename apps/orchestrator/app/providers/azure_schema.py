from __future__ import annotations

from copy import deepcopy
from typing import Any

_UNSUPPORTED_SCHEMA_KEYS = {
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
    "unevaluatedItems",
    "unevaluatedProperties",
    "uniqueItems",
}


def compile_azure_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Compile a permissive Pydantic JSON Schema into Azure strict-mode subset."""

    compiled = _compile_schema_node(deepcopy(schema))
    if not isinstance(compiled, dict):
        raise TypeError("Compiled Azure schema must be a JSON object.")
    return compiled


def _compile_schema_node(node: Any) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            return {"$ref": ref}

        compiled: dict[str, Any] = {}

        schema_type = node.get("type")
        if isinstance(schema_type, list):
            compiled["type"] = list(schema_type)
        elif isinstance(schema_type, str):
            compiled["type"] = schema_type

        if "description" in node and isinstance(node["description"], str):
            compiled["description"] = node["description"]

        if "enum" in node and isinstance(node["enum"], list):
            compiled["enum"] = list(node["enum"])
        elif "const" in node:
            compiled["enum"] = [node["const"]]

        if "anyOf" in node and isinstance(node["anyOf"], list):
            compiled["anyOf"] = [_compile_schema_node(item) for item in node["anyOf"]]

        if "items" in node:
            compiled["items"] = _compile_schema_node(node["items"])

        raw_properties = node.get("properties")
        if isinstance(raw_properties, dict):
            compiled_properties: dict[str, Any] = {}
            for key, value in raw_properties.items():
                compiled_properties[key] = _compile_schema_node(value)
            compiled["type"] = "object"
            compiled["properties"] = compiled_properties
            compiled["required"] = list(compiled_properties.keys())
            compiled["additionalProperties"] = False

        raw_defs = node.get("$defs")
        if isinstance(raw_defs, dict):
            compiled["$defs"] = {key: _compile_schema_node(value) for key, value in raw_defs.items()}

        for key, value in node.items():
            if key in {
                "$defs",
                "$ref",
                "additionalProperties",
                "anyOf",
                "const",
                "description",
                "enum",
                "items",
                "properties",
                "required",
                "title",
                "type",
            }:
                continue
            if key in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            if key == "additionalProperties" and "properties" not in node:
                if isinstance(value, bool):
                    compiled["additionalProperties"] = value
                continue
            if isinstance(value, (dict, list)):
                compiled[key] = _compile_schema_node(value)

        return compiled

    if isinstance(node, list):
        return [_compile_schema_node(item) for item in node]

    return node
