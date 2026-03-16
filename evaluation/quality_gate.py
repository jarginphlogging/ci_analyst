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
    "Synthesis Quality": 0.80,
}


def _normalize_metric_name(name: str) -> str:
    lowered = name.strip().lower()
    alias_map = {
        "sql correctness v2.1": "SQL Correctness",
        "hallucination v2.1": "Hallucination",
        "qa correctness v2.1": "QA Correctness",
        "synthesis quality v2.1": "Synthesis Quality",
        "decomposition quality v2.1": "decomposition_coverage",
        "execution_accuracy": "execution_accuracy",
        "decomposition_coverage": "decomposition_coverage",
        "key_value_presence": "key_value_presence",
        "sql_syntax_valid": "sql_syntax_valid",
        "sql correctness": "SQL Correctness",
        "hallucination": "Hallucination",
        "qa correctness": "QA Correctness",
        "synthesis quality": "Synthesis Quality",
        "summarization": "Synthesis Quality",
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


def _label_score(label: str) -> float:
    normalized = str(label).strip().lower()
    if normalized in {"correct", "grounded", "good", "complete", "pass", "true"}:
        return 1.0
    if normalized in {"partial"}:
        return 0.5
    if normalized in {"incorrect", "hallucinated", "bad", "poor", "fail", "false"}:
        return 0.0
    return 0.0


def _metric_map_from_logged_evaluations(evaluations: list[Any]) -> dict[str, float]:
    metrics: dict[str, list[float]] = {}
    for evaluation in evaluations:
        eval_name = _normalize_metric_name(str(getattr(evaluation, "eval_name", "")).strip())
        df = getattr(evaluation, "dataframe", pd.DataFrame())
        if not eval_name or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        values: list[float] = []
        if "score" in df.columns:
            numeric = pd.to_numeric(df["score"], errors="coerce").dropna()
            values = [float(item) for item in numeric.tolist()]
        elif "label" in df.columns:
            values = [_label_score(item) for item in df["label"].astype(str).tolist()]
        if not values:
            continue
        metrics.setdefault(eval_name, []).extend(values)
    return {name: sum(values) / max(1, len(values)) for name, values in metrics.items()}


def _fetch_metrics(client: Any, experiment_name: str | None = None) -> dict[str, float]:
    metrics: dict[str, float] = {}
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
                metrics.update(_metric_map_from_dataframe(df))
        except Exception:  # noqa: BLE001
            continue

    try:
        get_evaluations = getattr(client, "get_evaluations", None)
        if callable(get_evaluations):
            logged = get_evaluations()
            if isinstance(logged, list):
                logged_metrics = _metric_map_from_logged_evaluations(logged)
                for name, value in logged_metrics.items():
                    if name not in metrics:
                        metrics[name] = value
    except Exception:  # noqa: BLE001
        pass

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Phoenix quality gate")
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
