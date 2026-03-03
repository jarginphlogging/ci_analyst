from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.common_v2_1 import repo_root


@dataclass(frozen=True)
class GoldenExampleV21:
    input: str
    expected_plan: list[str]
    expected_sql_steps: list[str]
    expected_answer: str
    must_contain: list[str]
    difficulty: str
    category: str


def _as_list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_golden_examples(path: str | None = None) -> list[GoldenExampleV21]:
    dataset_path = Path(path).expanduser() if path else repo_root() / "evaluation" / "golden_examples_v2_1.yaml"
    if not dataset_path.exists():
        raise RuntimeError(f"Golden dataset file not found: {dataset_path}")
    try:
        import yaml  # type: ignore[import-untyped]
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("PyYAML is required. Install with `python -m pip install pyyaml`.") from error
    payload = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Golden dataset YAML must be a list of examples.")

    examples: list[GoldenExampleV21] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        examples.append(
            GoldenExampleV21(
                input=str(item.get("input", "")).strip(),
                expected_plan=_as_list_of_str(item.get("expected_plan")),
                expected_sql_steps=_as_list_of_str(item.get("expected_sql_steps")),
                expected_answer=str(item.get("expected_answer", "")).strip(),
                must_contain=_as_list_of_str(item.get("must_contain")),
                difficulty=str(item.get("difficulty", "moderate")).strip(),
                category=str(item.get("category", "general")).strip(),
            )
        )
    return [example for example in examples if example.input]


def to_dataset_records(examples: list[GoldenExampleV21]) -> list[dict[str, Any]]:
    return [
        {
            "input": example.input,
            "expected_plan": example.expected_plan,
            "expected_sql_steps": example.expected_sql_steps,
            "expected_answer": example.expected_answer,
            "must_contain": example.must_contain,
            "difficulty": example.difficulty,
            "category": example.category,
        }
        for example in examples
    ]

