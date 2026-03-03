from __future__ import annotations

import argparse
import sys
from typing import Any

import pandas as pd

THRESHOLDS = {
    "execution_accuracy": 0.80,
    "decomposition_coverage": 0.75,
    "key_value_presence": 0.85,
    "sql_syntax_valid": 0.95,
    "SQL Correctness": 0.80,
    "Hallucination": 0.85,
    "QA Correctness": 0.80,
    "Summarization": 0.80,
}


def _normalize_metric_name(name: str) -> str:
    lowered = name.strip().lower()
    alias_map = {
        "sql correctness v2.1": "SQL Correctness",
        "hallucination v2.1": "Hallucination",
        "qa correctness v2.1": "QA Correctness",
        "synthesis quality v2.1": "Summarization",
        "decomposition quality v2.1": "decomposition_coverage",
        "execution_accuracy": "execution_accuracy",
        "decomposition_coverage": "decomposition_coverage",
        "key_value_presence": "key_value_presence",
        "sql_syntax_valid": "sql_syntax_valid",
        "sql correctness": "SQL Correctness",
        "hallucination": "Hallucination",
        "qa correctness": "QA Correctness",
        "summarization": "Summarization",
    }
    return alias_map.get(lowered, name)


def _metric_map_from_dataframe(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {}
    metric_col = next(
        (col for col in ["eval_name", "metric", "name", "evaluator_name"] if col in df.columns),
        None,
    )
    score_col = next((col for col in ["mean", "score", "avg_score", "value"] if col in df.columns), None)
    if metric_col is None or score_col is None:
        return {}

    grouped = df.groupby(metric_col)[score_col].mean()
    metrics: dict[str, float] = {}
    for key, value in grouped.items():
        try:
            metrics[_normalize_metric_name(str(key))] = float(value)
        except Exception:  # noqa: BLE001
            continue
    return metrics


def _fetch_metrics(client: Any, experiment_name: str | None = None) -> dict[str, float]:
    methods = [
        "get_experiment_results_dataframe",
        "get_experiment_runs_dataframe",
        "get_experiments_dataframe",
    ]
    for method_name in methods:
        method = getattr(client, method_name, None)
        if method is None:
            continue
        try:
            if experiment_name:
                df = method(experiment_name=experiment_name)
            else:
                df = method()
            if isinstance(df, pd.DataFrame):
                metrics = _metric_map_from_dataframe(df)
                if metrics:
                    return metrics
        except Exception:  # noqa: BLE001
            continue
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Phoenix quality gate v2.1")
    parser.add_argument("--experiment-name", default=None, help="Optional Phoenix experiment name")
    args = parser.parse_args()

    try:
        import phoenix as px
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Phoenix dependency is required for quality gate.") from error

    client = px.Client()
    metrics = _fetch_metrics(client, experiment_name=args.experiment_name)
    if not metrics:
        print("No experiment metrics were found in Phoenix.")
        sys.exit(1)

    failed = False
    for name, threshold in THRESHOLDS.items():
        score = metrics.get(name)
        if score is None:
            print(f"[FAIL] {name}: missing metric")
            failed = True
            continue
        passed = score >= threshold
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: score={score:.4f}, threshold={threshold:.4f}")
        if not passed:
            failed = True

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

