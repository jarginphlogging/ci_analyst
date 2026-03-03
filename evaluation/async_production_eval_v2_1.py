from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from evaluation.llm_evaluators_v2_1 import (
    build_decomposition_classifier,
    build_judge,
    classify_hallucination,
    classify_sql_generation,
    classify_synthesis_quality,
)


def _ensure_output_dir() -> Path:
    output_dir = Path(__file__).resolve().parent / "flagged"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _safe_series(df: pd.DataFrame, column: str, default: Any = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default for _ in range(len(df))])


def _name_series(df: pd.DataFrame) -> pd.Series:
    return _safe_series(df, "name", "").astype(str)


def _build_decomposition_df(spans_df: pd.DataFrame) -> pd.DataFrame:
    t1 = spans_df[_name_series(spans_df).str.contains("t1_plan", na=False)].copy()
    return pd.DataFrame(
        {
            "question": _safe_series(t1, "attributes.input.value", "{}").astype(str),
            "sub_questions": _safe_series(t1, "attributes.output.value", "{}").astype(str),
            "context.span_id": _safe_series(t1, "context.span_id", ""),
        }
    )


def _build_sql_df(spans_df: pd.DataFrame) -> pd.DataFrame:
    t2 = spans_df[_name_series(spans_df).str.contains("t2_sql", na=False)].copy()
    return pd.DataFrame(
        {
            "question": _safe_series(t2, "attributes.input.value", "{}").astype(str),
            "query_gen": _safe_series(t2, "attributes.sql.query", "").astype(str),
            "response": _safe_series(t2, "attributes.output.value", "{}").astype(str),
            "context.span_id": _safe_series(t2, "context.span_id", ""),
        }
    )


def _build_synthesis_df(spans_df: pd.DataFrame) -> pd.DataFrame:
    t4 = spans_df[
        _name_series(spans_df).str.contains(r"pipeline\.t4_synthesis($|_final)", regex=True, na=False)
    ].copy()
    input_series = _safe_series(t4, "attributes.input.value", "{}").astype(str)
    output_series = _safe_series(t4, "attributes.output.value", "{}").astype(str)
    return pd.DataFrame(
        {
            "input": input_series,
            "output": output_series,
            "context": input_series,
            "context.span_id": _safe_series(t4, "context.span_id", ""),
        }
    )


def _normalize_span_eval_df(result_df: pd.DataFrame, *, span_ids: pd.Series) -> pd.DataFrame:
    df = result_df.copy()
    if "context.span_id" not in df.columns:
        df.insert(0, "context.span_id", span_ids.astype(str).tolist())
    else:
        df["context.span_id"] = df["context.span_id"].fillna(span_ids).astype(str)
    if "score" not in df.columns and "label" in df.columns:
        mapping = {
            "correct": 1.0,
            "grounded": 1.0,
            "good": 1.0,
            "complete": 1.0,
            "partial": 0.5,
            "incorrect": 0.0,
            "hallucinated": 0.0,
            "bad": 0.0,
            "poor": 0.0,
        }
        df["score"] = (
            df["label"]
            .astype(str)
            .str.strip()
            .str.lower()
            .map(mapping)
            .fillna(0.0)
            .astype(float)
        )
    columns = ["context.span_id", "score"]
    if "label" in df.columns:
        columns.append("label")
    if "explanation" in df.columns:
        columns.append("explanation")
    return df[columns]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run async Phoenix production evals (v2.1).")
    parser.add_argument("--hours", type=int, default=1, help="Lookback window in hours")
    args = parser.parse_args()

    try:
        import phoenix as px
        from phoenix.trace import SpanEvaluations
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Phoenix dependencies are required for async production eval.") from error

    client = px.Client()
    spans_df = client.get_spans_dataframe(
        project_name="cortex-analyst-pipeline",
        start_time=datetime.now() - timedelta(hours=max(1, args.hours)),
    )

    if spans_df.empty:
        print("No spans found for lookback window.")
        return

    judge = build_judge()

    decomp_df = _build_decomposition_df(spans_df)
    sql_df = _build_sql_df(spans_df)
    synth_df = _build_synthesis_df(spans_df)

    decomp_classifier = build_decomposition_classifier(judge)
    decomp_results = decomp_classifier.evaluate(dataframe=decomp_df)
    sql_results = classify_sql_generation(sql_df, judge)
    hallucination_results = classify_hallucination(synth_df[["input", "output", "context"]], judge)
    synthesis_results = classify_synthesis_quality(
        pd.DataFrame({"input": synth_df["context"], "output": synth_df["output"]}),
        judge,
    )

    client.log_evaluations(
        SpanEvaluations(
            dataframe=_normalize_span_eval_df(
                decomp_results,
                span_ids=decomp_df["context.span_id"],
            ),
            eval_name="Decomposition Quality v2.1",
        ),
        SpanEvaluations(
            dataframe=_normalize_span_eval_df(
                sql_results,
                span_ids=sql_df["context.span_id"],
            ),
            eval_name="SQL Correctness v2.1",
        ),
        SpanEvaluations(
            dataframe=_normalize_span_eval_df(
                hallucination_results,
                span_ids=synth_df["context.span_id"],
            ),
            eval_name="Hallucination v2.1",
        ),
        SpanEvaluations(
            dataframe=_normalize_span_eval_df(
                synthesis_results,
                span_ids=synth_df["context.span_id"],
            ),
            eval_name="Synthesis Quality v2.1",
        ),
    )

    flagged = []
    for result_df in (sql_results, hallucination_results):
        if "label" in result_df:
            flagged.append(result_df[result_df["label"].isin(["incorrect", "hallucinated"])])
    flagged_df = pd.concat(flagged) if flagged else pd.DataFrame()
    if not flagged_df.empty:
        output_dir = _ensure_output_dir()
        output_file = output_dir / f"review_{datetime.now().strftime('%Y%m%d')}.csv"
        flagged_df.to_csv(output_file, index=False)
        print(f"Flagged traces exported: {output_file}")
    else:
        print("No flagged traces in this run.")


if __name__ == "__main__":
    main()
