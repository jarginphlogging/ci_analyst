from __future__ import annotations

import json
from typing import Any


def extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    fenced_start = stripped.find("```json")
    if fenced_start >= 0:
        start = stripped.find("{", fenced_start)
        end_fence = stripped.find("```", fenced_start + 7)
        if start >= 0 and end_fence > start:
            return stripped[start:end_fence].strip()

    start = stripped.find("{")
    if start < 0:
        raise ValueError("No JSON object found in model output.")

    depth = 0
    for index in range(start, len(stripped)):
        char = stripped[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    raise ValueError("Unbalanced JSON object in model output.")


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = extract_json_candidate(text)
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Model output JSON must be an object.")
    return payload


def as_string_list(value: Any, *, fallback: list[str] | None = None, max_items: int = 5) -> list[str]:
    if not isinstance(value, list):
        return fallback or []
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:max_items]

