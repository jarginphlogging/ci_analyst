from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from evaluation.code_evaluators_v2_1 import (
    decomposition_coverage,
    execution_accuracy,
    key_value_presence,
    sql_syntax_valid,
)
from evaluation.common_v2_1 import ensure_orchestrator_path
from evaluation.golden_dataset_v2_1 import load_golden_examples, to_dataset_records
from evaluation.llm_evaluators_v2_1 import (
    build_decomposition_classifier,
    build_judge,
    classify_hallucination,
    classify_qa,
    classify_sql_generation,
    classify_synthesis_quality,
)

ensure_orchestrator_path()

from app.models import ChatTurnRequest  # noqa: E402
from app.services.dependencies import create_dependencies  # noqa: E402
from app.services.orchestrator import ConversationalOrchestrator  # noqa: E402


async def _run_turn(question: str) -> dict[str, Any]:
    orchestrator = ConversationalOrchestrator(create_dependencies())
    turn = await orchestrator.run_turn(
        ChatTurnRequest(
            sessionId=uuid4(),
            message=question,
        )
    )
    response = turn.response
    trace = response.trace or []
    plan_step = next((step for step in trace if step.id == "t1"), None)
    sql_step = next((step for step in trace if step.id == "t2"), None)
    validation_step = next((step for step in trace if step.id == "t3"), None)
    sql_steps: list[str] = []
    if sql_step and sql_step.stageOutput and isinstance(sql_step.stageOutput, dict):
        for item in sql_step.stageOutput.get("steps", []):
            if isinstance(item, dict):
                candidate = str(item.get("sqlPreview", "")).strip()
                if candidate:
                    sql_steps.append(candidate)
    if sql_step and sql_step.sql:
        sql_steps.insert(0, sql_step.sql)
    deduped_sql_steps: list[str] = []
    for item in sql_steps:
        if item not in deduped_sql_steps:
            deduped_sql_steps.append(item)
    plan_steps: list[str] = []
    if plan_step and plan_step.stageOutput and isinstance(plan_step.stageOutput, dict):
        for item in plan_step.stageOutput.get("steps", []):
            if isinstance(item, dict):
                goal = str(item.get("goal", "")).strip()
                if goal:
                    plan_steps.append(goal)
    return {
        "plan_steps": plan_steps,
        "sql_steps": deduped_sql_steps[:6],
        "sql_results_summary": sql_step.stageOutput if sql_step else {},
        "validation": validation_step.stageOutput if validation_step else {},
        "final_answer": response.answer,
        "synthesis_context": (
            trace[-1].stageInput.get("resultSummary", {}) if trace and trace[-1].stageInput else {}
        ),
    }


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return str(value)


def _extract_question(example_input: Any) -> str:
    if isinstance(example_input, dict):
        candidate = str(example_input.get("input", "")).strip()
        if candidate:
            return candidate
    return str(example_input or "").strip()


def _build_run_dataframe(experiment: Any, *, experiment_name: str, pd: Any) -> Any:
    rows: list[dict[str, Any]] = []
    runs = getattr(experiment, "runs", {}) or {}
    dataset = getattr(experiment, "dataset", None)
    examples = getattr(dataset, "examples", {}) if dataset is not None else {}
    for run in runs.values():
        output = run.output if isinstance(run.output, dict) else {}
        example = examples.get(run.dataset_example_id)
        example_input = getattr(example, "input", {})
        expected = getattr(example, "output", {})
        trace_id = getattr(run, "trace_id", None) or str(
            uuid5(
                NAMESPACE_URL,
                f"{experiment_name}:{run.dataset_example_id}:{run.repetition_number}",
            )
        )
        rows.append(
            {
                "context.trace_id": str(trace_id),
                "question": _extract_question(example_input),
                "plan_steps": _to_text(output.get("plan_steps", [])),
                "sql_steps": _to_text(output.get("sql_steps", [])),
                "sql_results_summary": _to_text(output.get("sql_results_summary", {})),
                "final_answer": _to_text(output.get("final_answer", "")),
                "synthesis_context": _to_text(output.get("synthesis_context", {})),
                "expected_answer": _to_text(expected.get("expected_answer", "")),
            }
        )
    return pd.DataFrame(rows)


def _normalize_trace_eval_df(
    result_df: Any,
    *,
    trace_ids: Any,
    label_scores: dict[str, float] | None = None,
) -> Any:
    df = result_df.copy()
    if "context.trace_id" not in df.columns:
        df.insert(0, "context.trace_id", trace_ids.astype(str).tolist())
    else:
        df["context.trace_id"] = df["context.trace_id"].fillna(trace_ids).astype(str)

    if "score" not in df.columns:
        if "label" in df.columns:
            mapping = {
                "correct": 1.0,
                "grounded": 1.0,
                "good": 1.0,
                "complete": 1.0,
                "partial": 0.5,
                "poor": 0.0,
                "incorrect": 0.0,
                "hallucinated": 0.0,
                "bad": 0.0,
            }
            if label_scores:
                mapping.update({key.lower(): value for key, value in label_scores.items()})
            df["score"] = (
                df["label"]
                .astype(str)
                .str.strip()
                .str.lower()
                .map(mapping)
                .fillna(0.0)
                .astype(float)
            )
        else:
            df["score"] = 0.0

    columns = ["context.trace_id", "score"]
    if "label" in df.columns:
        columns.append("label")
    if "explanation" in df.columns:
        columns.append("explanation")
    return df[columns]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phoenix Tier 3 experiment v2.1.")
    parser.add_argument("--name", required=True, help="Experiment name")
    parser.add_argument("--description", default="", help="Experiment description")
    parser.add_argument("--dataset", default="cortex-analyst-golden-v2-1", help="Phoenix dataset name")
    parser.add_argument("--dataset-path", default=None, help="Optional local YAML fallback")
    args = parser.parse_args()

    try:
        import pandas as pd
        import phoenix as px
        from phoenix.experiments import run_experiment
        from phoenix.trace import TraceEvaluations
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Phoenix experiment dependencies are required.") from error

    client = px.Client()
    dataset = None
    try:
        dataset = client.get_dataset(name=args.dataset)
    except Exception:  # noqa: BLE001
        examples = load_golden_examples(args.dataset_path)
        records = to_dataset_records(examples)
        client.upload_dataset(dataset_name=args.dataset, dataframe=pd.DataFrame(records))
        dataset = client.get_dataset(name=args.dataset)

    judge = build_judge()

    def task(input_row: dict[str, Any]) -> dict[str, Any]:
        question = str(input_row.get("input", "")).strip()
        return _run_async(_run_turn(question))

    experiment = run_experiment(
        dataset=dataset,
        task=task,
        evaluators=[
            execution_accuracy,
            decomposition_coverage,
            key_value_presence,
            sql_syntax_valid,
        ],
        experiment_name=args.name,
        experiment_description=args.description,
    )

    run_df = _build_run_dataframe(experiment, experiment_name=args.name, pd=pd)
    if not run_df.empty:
        decomp_df = pd.DataFrame(
            {
                "context.trace_id": run_df["context.trace_id"].astype(str),
                "question": run_df["question"].astype(str),
                "sub_questions": run_df["plan_steps"].astype(str),
            }
        )
        decomp_classifier = build_decomposition_classifier(judge)
        decomp_results = decomp_classifier.evaluate(dataframe=decomp_df)

        sql_df = pd.DataFrame(
            {
                "context.trace_id": run_df["context.trace_id"].astype(str),
                "question": run_df["question"].astype(str),
                "query_gen": run_df["sql_steps"].astype(str),
                "response": run_df["sql_results_summary"].astype(str),
            }
        )
        synth_df = pd.DataFrame(
            {
                "context.trace_id": run_df["context.trace_id"].astype(str),
                "input": run_df["question"].astype(str),
                "output": run_df["final_answer"].astype(str),
                "context": run_df["synthesis_context"].astype(str),
                "query": run_df["question"].astype(str),
                "reference": run_df["expected_answer"].astype(str),
                "sampled_answer": run_df["final_answer"].astype(str),
            }
        )

        sql_results = classify_sql_generation(sql_df[["question", "query_gen", "response"]], judge)
        hallucination_results = classify_hallucination(synth_df[["input", "output", "context"]], judge)
        qa_results = classify_qa(synth_df[["query", "reference", "sampled_answer"]], judge)
        synthesis_results = classify_synthesis_quality(
            pd.DataFrame({"input": synth_df["context"], "output": synth_df["output"]}),
            judge,
        )

        trace_ids = run_df["context.trace_id"].astype(str)
        client.log_evaluations(
            TraceEvaluations(
                eval_name="Decomposition Quality v2.1",
                dataframe=_normalize_trace_eval_df(decomp_results, trace_ids=trace_ids),
            ),
            TraceEvaluations(
                eval_name="SQL Correctness v2.1",
                dataframe=_normalize_trace_eval_df(sql_results, trace_ids=trace_ids),
            ),
            TraceEvaluations(
                eval_name="Hallucination v2.1",
                dataframe=_normalize_trace_eval_df(
                    hallucination_results,
                    trace_ids=trace_ids,
                    label_scores={"grounded": 1.0, "hallucinated": 0.0},
                ),
            ),
            TraceEvaluations(
                eval_name="QA Correctness v2.1",
                dataframe=_normalize_trace_eval_df(qa_results, trace_ids=trace_ids),
            ),
            TraceEvaluations(
                eval_name="Synthesis Quality v2.1",
                dataframe=_normalize_trace_eval_df(synthesis_results, trace_ids=trace_ids),
            ),
        )

    print(f"Experiment '{args.name}' completed.")


if __name__ == "__main__":
    main()
