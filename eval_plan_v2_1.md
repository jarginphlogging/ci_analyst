# Cortex Analyst Evaluation Plan v2.1 — Three-Tier Architecture (Implementation-Ready)

## Intent Preservation

This v2.1 document preserves the original plan's strategy and adds back implementation specificity:

- three-tier evaluation model
- deterministic + LLM-as-judge evaluators
- runtime inline checks + async production eval + golden dataset correctness eval
- feedback flywheel from production failures to golden dataset
- Phoenix as governance/release authority
- legacy eval harness retained for fast developer loops

Only adaptation: node and contract mapping now match the actual orchestrator code path.

---

## Ground Truth Model (Unchanged)

```
                        Has ground     Can use      Blocks
                        truth?         LLM judge?   response?    Runs when?
                        ─────────      ──────────   ─────────    ──────────
Tier 1: Inline          No             No           Yes          Every request
Tier 2: Async Prod      No             Yes          No           After response
Tier 3: Golden Dataset  Yes            Yes          No           CI/CD + nightly
```

This still means:

- Tier 1: "Is output structurally safe and policy-valid?"
- Tier 2: "Is output internally consistent with pipeline context?"
- Tier 3: "Is output correct against known truth?"

---

## Real Pipeline Mapping (`t1..t4`)

Current runtime stages:

```
User Question → [t1 Plan] → [t2 SQL Gen + Execute] → [t3 Validation] → [t4 Synthesis]
```

### Stage Ownership

| Stage | File / function(s) | Primary output |
|------|------|------|
| `t1` Plan | `PlannerStage.create_plan` | `TurnExecutionContext.plan`, `presentation_intent` |
| `t2` SQL Gen + Execute | `SqlExecutionStage.run_sql` (+ generator + retries) | `list[SqlExecutionResult]`, retry feedback |
| `t3` Validation | `ValidationStage.validate_results` | `ValidationResult` |
| `t4` Synthesis | `SynthesisStage.build_response` | `AgentResponse` |

### Existing Trace Contracts (must be preserved)

- UI trace payload: `AgentResponse.trace[]` (`TraceStep`) with `stageInput` / `stageOutput`
- LLM trace payload: `LlmTraceCollector` entries (`plan_generation`, `sql_generation`, `synthesis_final`)

Phoenix spans must be additive, not a replacement.

---

## Tier 1: Inline Checks (Hot Path)

Context: current stage I/O only, no ground truth, deterministic only.

### Check Matrix (Specific)

| Stage | Check | Rule | Fail Action |
|------|------|------|------|
| `t1` | plan_count | `1 <= len(plan) <= 5` | block with planner guidance |
| `t1` | plan_step_shape | each step has non-empty `id`, `goal` | block |
| `t2` | sql_syntax | SQL parses as `SELECT`/`WITH` | retry/skip per step policy |
| `t2` | sql_policy | allowlist/restricted cols/read-only/limit | block step (existing guardrails) |
| `t2` | result_sanity | rows > 0 when not clarification; rowCount <= policy max; cell size <= 1MB | truncate/warn or block |
| `t3` | validation_contract | checks list not empty; pass boolean present | block |
| `t4` | answer_sanity | non-empty answer, min length, not known error text | fallback deterministic answer |
| `t4` | pii_scan | no SSN/account/card patterns | redact + warning |

### Recommended Function Signatures

```python
def check_plan_sanity(plan: list[dict]) -> tuple[bool, str]: ...
def check_sql_syntax(sql: str) -> tuple[bool, str]: ...
def check_result_sanity(rows: list[dict], row_count: int, max_rows: int) -> tuple[bool, str]: ...
def check_validation_contract(passed: bool, checks: list[str]) -> tuple[bool, str]: ...
def check_answer_sanity(answer: str) -> tuple[bool, str]: ...
def check_pii(answer: str) -> tuple[bool, str]: ...
```

### Tier 1 Logging Requirements

For each check:

- add result to existing `TraceStep.stageOutput`/`qualityChecks`
- add Phoenix span event:
  - `eval.check.name`
  - `eval.check.passed`
  - `eval.check.reason`

---

## Dual Tracing Spec (UI + Phoenix)

### Phoenix Packages

- `arize-phoenix`
- `arize-phoenix-otel`
- `arize-phoenix-evals`
- `openinference-instrumentation-openai` (optional/limited utility for current provider stack)

### Span Structure

Use one parent span per request/turn, child spans for `t1..t4`.

Required attributes:

- `eval.stage`: `t1|t2|t3|t4`
- `input.value`: compact JSON string
- `output.value`: compact JSON string

Stage-specific:

- `t2`: `sql.query`, `result.row_count`, `result.columns`, `retry.count`
- `t3`: `validation.passed`, `validation.check_count`
- `t4`: `response.confidence`, `response.table_count`, `response.artifact_count`

### Duplication Rule

Build stage payload once, emit to both:

1. existing `TraceStep` payloads
2. Phoenix span attributes/events

No duplicate stage business logic.

---

## Tier 2: Async Production Eval (Phoenix)

Context: full production traces/spans, no ground truth.

### Evaluators

| Evaluator | Tier 2 meaning |
|------|------|
| Decomposition quality | whether `t1` plan covers intent |
| SQL correctness | whether `t2` SQL is plausible given step goal and execution result |
| Hallucination | whether `t4` answer is grounded in pipeline-produced context |
| QA correctness | whether `t4` answer addresses question given pipeline context |
| Synthesis quality | coherence/completeness of final answer |

### DataFrame Contract Mapping

#### Decomposition Quality

- `question`: from `t1` stage input message
- `sub_questions`: from `t1` stage output steps/goals (serialized)

#### SQL Generation Eval

- `question`: step goal (or mapped prompt step)
- `query_gen`: generated SQL
- `response`: execution result summary (`row_count`, sample rows, errors)

#### Hallucination Eval

- `input`: user question
- `output`: final answer
- `context`: synthesized package / result summaries used by `t4`

#### QA Eval

- `query`: user question
- `reference`: pipeline-produced evidence context
- `sampled_answer`: final answer

### Batch Execution Defaults

- `concurrency=20`
- `provide_explanation=True`
- hourly backfill window default: `--hours 1`

### Flagging Rules

Write to `evaluation/flagged/review_YYYYMMDD.csv` when:

- hallucination label is hallucinated
- SQL correctness label is incorrect
- QA correctness label is incorrect

---

## Tier 2 Implementation Skeleton (Reference)

```python
from datetime import datetime, timedelta
import pandas as pd
import phoenix as px
from phoenix.evals import llm_classify, create_classifier
from phoenix.trace import SpanEvaluations

def run_async_eval(hours: int = 1) -> None:
    client = px.Client()
    spans_df = client.get_spans_dataframe(
        project_name="cortex-analyst-pipeline",
        start_time=datetime.now() - timedelta(hours=hours),
    )

    # Build t1/t2/t4 evaluator frames from mapped span attributes.
    decomp_df = build_decomposition_df(spans_df)
    sql_df = build_sql_df(spans_df)
    synth_df = build_synthesis_df(spans_df)

    decomp_eval = create_classifier(
        name="decomposition_quality",
        prompt_template=(
            "Question: {question}\n"
            "Plan: {sub_questions}\n"
            "Do these steps fully cover intent with minimal redundancy?"
        ),
        choices={"complete": 1.0, "partial": 0.5, "poor": 0.0},
    )
    decomp_results = decomp_eval.evaluate(dataframe=decomp_df)

    sql_results = llm_classify(dataframe=sql_df, template=SQL_GEN_EVAL_PROMPT_TEMPLATE, concurrency=20)
    hallucination_results = llm_classify(dataframe=synth_df, template=HALLUCINATION_PROMPT_TEMPLATE, concurrency=20)
    qa_results = llm_classify(dataframe=synth_df, template=QA_PROMPT_TEMPLATE, concurrency=20)

    client.log_evaluations(
        SpanEvaluations(dataframe=decomp_results, eval_name="Decomposition Quality"),
        SpanEvaluations(dataframe=sql_results, eval_name="SQL Correctness"),
        SpanEvaluations(dataframe=hallucination_results, eval_name="Hallucination"),
        SpanEvaluations(dataframe=qa_results, eval_name="QA Correctness"),
    )
```

---

## Tier 3: Golden Dataset Correctness (Phoenix Experiments)

Context: full task output + known-correct references.
Authority: release/merge gate.

### Golden Dataset v2.1 Schema

```yaml
- input: "user question"
  expected_plan:
    - "step 1 goal"
    - "step 2 goal"
  expected_sql_steps:
    - "SELECT ..."
    - "SELECT ..."
  expected_answer: "known-correct answer"
  must_contain: ["keyword1", "keyword2"]
  difficulty: "simple|moderate|complex"
  category: "domain"
```

Distribution baseline:

- 4 simple
- 4 moderate
- 2 complex

### Deterministic Evaluators (Required)

- `execution_accuracy(output, expected) -> float`
- `decomposition_coverage(output, expected) -> float`
- `key_value_presence(output, expected) -> float`
- `sql_syntax_valid(output) -> float|bool`

### LLM Evaluators (Required)

- SQL generation quality
- hallucination/groundedness
- QA correctness
- synthesis quality
- decomposition quality classifier

### Tier 3 Task Output Contract

`pipeline_task` should return normalized fields:

- `plan_steps`
- `sql_steps`
- `sql_results_summary`
- `validation`
- `final_answer`
- `synthesis_context`

---

## Tier 3 Experiment Skeleton (Reference)

```python
from phoenix.experiments import run_experiment

async def pipeline_task(input_row: dict) -> dict:
    question = input_row["input"]
    # Run full orchestrator path and normalize outputs for evaluators.
    output = await run_orchestrator_turn(question)
    return normalize_for_eval(output)

experiment = run_experiment(
    dataset=dataset,
    task=pipeline_task,
    evaluators=[
        execution_accuracy,
        decomposition_coverage,
        key_value_presence,
        sql_syntax_valid,
        sql_llm_eval,
        hallucination_eval,
        qa_eval,
        synthesis_eval,
    ],
    experiment_name="pipeline-v2.1",
)
```

---

## Quality Gate (Phoenix Authority)

Release gate thresholds:

```python
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
```

Behavior:

- fail build if any threshold is unmet
- Phoenix gate is authoritative

Legacy eval harness remains non-authoritative advisory signal.

---

## Legacy + Phoenix Parallel Model

### Authority Split

- Phoenix (Tier 3): merge/release authority
- legacy eval harness: fast feedback only

### Operational Rule

If legacy and Phoenix disagree:

- release decision follows Phoenix
- disagreement is logged for eval calibration

---

## How the Three Tiers Work Together (Restored)

```
              Tier 1 (Inline)              Tier 2 (Async)              Tier 3 (Golden)
              ─────────────────            ─────────────────           ─────────────────
Ground truth  None                         None                        Full
Judge?        No                           Yes                         Yes
Judge sees    Current stage I/O            Pipeline outputs            Pipeline outputs + correct refs
Catches       Broken/policy-invalid        Internally inconsistent     Actually incorrect outputs
              outputs                      outputs                      (even if internally consistent)
```

Example failure chain:

1. `t2` generates wrong-but-valid SQL.
2. `t3` validation passes structurally.
3. `t4` faithfully summarizes wrong result.
4. Tier 2 may pass groundedness.
5. Tier 3 fails execution accuracy and QA correctness against golden truth.

---

## Flow Between Tiers

```
Production request
       │
       ▼
Tier 1 inline checks ── block/fallback on structural/policy failure
       │
       ▼
User response delivered
       │
       ▼
Tier 2 async eval ── flagged traces for review
       │
       ▼
Confirmed failures promoted to golden dataset
       │
       ▼
Tier 3 experiment + CI gate prevents regressions
```

---

## Implementation Timeline (Restored)

| Week | Focus | Deliverable |
|------|------|------|
| 1 | Contract lock + dual tracing | UI trace preserved, Phoenix spans visible |
| 2 | Tier 1 inline checks | deterministic runtime guard coverage for `t1..t4` |
| 3 | Tier 2 async LLM evals | hourly production scoring + flagged exports |
| 4 | Tier 3 deterministic evaluators + 10 golden cases | first correctness experiment |
| 5 | Tier 3 LLM evaluators + CI gate | Phoenix-authoritative PR/nightly gate |
| 6 | Eval-the-evals calibration | agreement report + tuning backlog |
| Ongoing | Review flywheel | golden dataset expansion and threshold tuning |

---

## Acceptance Checklist

1. UI trace remains unchanged in payload shape.
2. Phoenix spans exist for `t1..t4` with required attributes.
3. Tier 1 checks run inline and are visible in both trace systems.
4. Tier 2 async script logs evaluator scores and flagged traces.
5. Tier 3 experiment runs end-to-end with deterministic + LLM evaluators.
6. CI fails on Phoenix threshold regression.
7. Legacy eval still runs quickly for developer loop.

