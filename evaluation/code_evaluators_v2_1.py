from __future__ import annotations

import asyncio
import re
from typing import Any

import pandas as pd

from evaluation.common_v2_1 import ensure_orchestrator_path

ensure_orchestrator_path()

from app.config import settings  # noqa: E402
from app.providers.factory import build_provider_bundle  # noqa: E402

try:
    from phoenix.evals import create_evaluator
except Exception:  # noqa: BLE001
    def create_evaluator(*_args: Any, **_kwargs: Any):  # type: ignore[misc]
        def _decorator(func):
            return func
        return _decorator


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _sql_executor():
    mode = settings.provider_mode
    if mode == "mock":
        mode = "sandbox"
    bundle = build_provider_bundle(mode)
    return bundle.sql_fn


def _execute_sql(sql: str) -> pd.DataFrame:
    rows = _run_async(_sql_executor()(sql))
    return pd.DataFrame(rows)


def _normalize_text_tokens(items: list[str]) -> set[str]:
    tokens: set[str] = set()
    for item in items:
        for token in re.findall(r"[a-z0-9_]{3,}", str(item).lower()):
            tokens.add(token)
    return tokens


@create_evaluator(name="execution_accuracy", kind="CODE")
def execution_accuracy(output: dict[str, Any], expected: dict[str, Any]) -> float:
    sql_steps = output.get("sql_steps")
    expected_sql_steps = expected.get("expected_sql_steps")
    if not isinstance(sql_steps, list) or not isinstance(expected_sql_steps, list) or not expected_sql_steps:
        return 0.0

    limit = min(len(sql_steps), len(expected_sql_steps))
    scores: list[float] = []
    for index in range(limit):
        generated_sql = str(sql_steps[index] or "").strip()
        golden_sql = str(expected_sql_steps[index] or "").strip()
        if not generated_sql or not golden_sql:
            scores.append(0.0)
            continue
        try:
            gen_df = _execute_sql(generated_sql)
            exp_df = _execute_sql(golden_sql)
            if exp_df.empty and gen_df.empty:
                scores.append(1.0)
                continue
            if exp_df.empty != gen_df.empty:
                scores.append(0.0)
                continue
            overlap_columns = [column for column in exp_df.columns if column in gen_df.columns]
            if not overlap_columns:
                scores.append(0.0)
                continue
            lhs = gen_df[overlap_columns].copy().astype(str)
            rhs = exp_df[overlap_columns].copy().astype(str)
            lhs_rows = set(tuple(row) for row in lhs.to_numpy())
            rhs_rows = set(tuple(row) for row in rhs.to_numpy())
            if not rhs_rows:
                scores.append(1.0 if not lhs_rows else 0.0)
                continue
            scores.append(len(lhs_rows & rhs_rows) / max(1, len(rhs_rows)))
        except Exception:  # noqa: BLE001
            scores.append(0.0)
    return sum(scores) / max(1, len(scores))


@create_evaluator(name="decomposition_coverage", kind="CODE")
def decomposition_coverage(output: dict[str, Any], expected: dict[str, Any]) -> float:
    actual = output.get("plan_steps")
    reference = expected.get("expected_plan")
    if not isinstance(actual, list) or not isinstance(reference, list):
        return 0.0
    reference_tokens = _normalize_text_tokens([str(item) for item in reference])
    if not reference_tokens:
        return 1.0
    actual_tokens = _normalize_text_tokens([str(item) for item in actual])
    return len(actual_tokens & reference_tokens) / max(1, len(reference_tokens))


@create_evaluator(name="key_value_presence", kind="CODE")
def key_value_presence(output: dict[str, Any], expected: dict[str, Any]) -> float:
    answer = str(output.get("final_answer", "")).lower()
    must_contain = expected.get("must_contain")
    if not isinstance(must_contain, list) or not must_contain:
        return 1.0
    found = sum(1 for token in must_contain if str(token).lower() in answer)
    return found / max(1, len(must_contain))


@create_evaluator(name="sql_syntax_valid", kind="CODE")
def sql_syntax_valid(output: dict[str, Any], _expected: dict[str, Any] | None = None) -> float:
    sql_steps = output.get("sql_steps")
    if not isinstance(sql_steps, list) or not sql_steps:
        return 0.0
    valid_count = 0
    for sql in sql_steps:
        text = str(sql or "").strip().lower()
        if text.startswith("select") or text.startswith("with"):
            valid_count += 1
    return valid_count / max(1, len(sql_steps))

