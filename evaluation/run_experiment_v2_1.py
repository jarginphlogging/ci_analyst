from __future__ import annotations

import argparse
import asyncio
from typing import Any
from uuid import uuid4

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

    # Optional post-experiment LLM evaluation pass for richer scoring.
    outputs_df = experiment.get_output_dataframe() if hasattr(experiment, "get_output_dataframe") else None
    if outputs_df is not None and len(outputs_df):
        def _column(name: str, fallback: Any = ""):
            if name in outputs_df:
                return outputs_df[name]
            return pd.Series([fallback for _ in range(len(outputs_df))])

        decomp_df = pd.DataFrame(
            {
                "question": _column("input.input", "").astype(str),
                "sub_questions": _column("output.plan_steps", "[]").astype(str),
            }
        )
        decomp_classifier = build_decomposition_classifier(judge)
        decomp_results = decomp_classifier.evaluate(dataframe=decomp_df)

        sql_df = pd.DataFrame(
            {
                "question": _column("input.input", "").astype(str),
                "query_gen": _column("output.sql_steps", "[]").astype(str),
                "response": _column("output.sql_results_summary", "{}").astype(str),
            }
        )
        synth_df = pd.DataFrame(
            {
                "input": _column("input.input", "").astype(str),
                "output": _column("output.final_answer", "").astype(str),
                "context": _column("output.synthesis_context", "{}").astype(str),
                "query": _column("input.input", "").astype(str),
                "reference": _column("expected.expected_answer", "").astype(str),
                "sampled_answer": _column("output.final_answer", "").astype(str),
            }
        )
        classify_sql_generation(sql_df, judge)
        classify_hallucination(synth_df[["input", "output", "context"]], judge)
        classify_qa(synth_df[["query", "reference", "sampled_answer"]], judge)
        classify_synthesis_quality(
            pd.DataFrame({"input": synth_df["context"], "output": synth_df["output"]}),
            judge,
        )
        _ = decomp_results

    print(f"Experiment '{args.name}' completed.")


if __name__ == "__main__":
    main()
