from __future__ import annotations

import argparse
from typing import Any

import pandas as pd


def _fetch_annotation_df(client: Any) -> pd.DataFrame:
    for method_name in ["get_annotations_dataframe", "get_trace_annotations_dataframe", "get_spans_dataframe"]:
        method = getattr(client, method_name, None)
        if method is None:
            continue
        try:
            df = method()
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame()


def _cohen_kappa(lhs: list[str], rhs: list[str]) -> float:
    try:
        from sklearn.metrics import cohen_kappa_score
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("scikit-learn is required to compute Cohen's kappa.") from error
    return float(cohen_kappa_score(lhs, rhs))


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval-the-evals calibration report v2.1")
    parser.add_argument("--min-agreement", type=float, default=0.80)
    args = parser.parse_args()

    try:
        import phoenix as px
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Phoenix dependency required.") from error

    client = px.Client()
    df = _fetch_annotation_df(client)
    if df.empty:
        print("No annotation data available.")
        return

    evaluator_col = next((c for c in ["evaluator_name", "eval_name", "metric"] if c in df.columns), None)
    human_col = next((c for c in ["human_label", "annotation_label", "label_human"] if c in df.columns), None)
    judge_col = next((c for c in ["judge_label", "label", "llm_label"] if c in df.columns), None)
    if not evaluator_col or not human_col or not judge_col:
        raise RuntimeError("Could not identify evaluator/human/judge columns in annotation dataframe.")

    report_rows: list[dict[str, Any]] = []
    for evaluator_name, chunk in df.groupby(evaluator_col):
        human = [str(v) for v in chunk[human_col].fillna("missing").tolist()]
        judge = [str(v) for v in chunk[judge_col].fillna("missing").tolist()]
        if not human:
            continue
        matches = sum(1 for lhs, rhs in zip(human, judge) if lhs == rhs)
        agreement = matches / max(1, len(human))
        kappa = _cohen_kappa(human, judge)
        report_rows.append(
            {
                "evaluator": str(evaluator_name),
                "sample_count": len(human),
                "agreement": round(agreement, 4),
                "kappa": round(kappa, 4),
                "needs_tuning": agreement < args.min_agreement,
            }
        )

    report = pd.DataFrame(report_rows).sort_values(by="agreement", ascending=True)
    print(report.to_string(index=False))
    weak = report[report["needs_tuning"] == True]  # noqa: E712
    if not weak.empty:
        print("\nEvaluators below agreement threshold:")
        print(weak[["evaluator", "agreement", "kappa"]].to_string(index=False))


if __name__ == "__main__":
    main()
