# Claude Code Prompts v2.1 — Evaluation Pipeline Implementation (Implementation-Ready)

## How To Use This

These are sequential prompts. Run in order.  
They preserve the original plan intent and add execution detail adapted to current `t1..t4` contracts.

Do not modify:

- `eval_plan.md`
- `eval_prompts.md`
- `eval_plan_v2.md`
- `eval_prompts_v2.md`

Use these prompts to implement v2.1 deliverables.

---

## Prompt 0: Orientation + Contract Map (`t1..t4`)

> Read `eval_plan_v2_1.md` and current orchestrator code.  
> Create `docs/eval_code_mapping_v2_1.md` with:
>
> 1. Exact stage mapping:
>    - `t1`: planner
>    - `t2`: SQL generation + execution
>    - `t3`: validation
>    - `t4`: synthesis
> 2. Stage I/O contracts (real field names and types from code)
> 3. Existing trace payload structures:
>    - `TraceStep.stageInput/stageOutput`
>    - `LlmTraceCollector` entries
> 4. Proposed Phoenix span attribute schema
> 5. Where to insert instrumentation with no business-logic duplication
>
> Do not change code yet.

Why this prompt exists: force exact contract grounding before implementation.

---

## Prompt 1: Dual Tracing (Keep Existing UI Trace + Add Phoenix)

> Reference `docs/eval_code_mapping_v2_1.md`.  
> Add Phoenix tracing while preserving existing UI trace behavior.
>
> Setup:
>
> - Install Python deps:
>   - `arize-phoenix`
>   - `arize-phoenix-otel`
>   - `arize-phoenix-evals`
>   - `openinference-instrumentation-openai`
> - Create `apps/orchestrator/app/tracing.py` to initialize tracer once.
>
> Instrument stages with child spans:
>
> - `t1_plan`
> - `t2_sql`
> - `t3_validation`
> - `t4_synthesis`
>
> Required span attributes:
>
> - `eval.stage`
> - `input.value`
> - `output.value`
>
> Stage-specific attributes:
>
> - `t2`: `sql.query`, `result.row_count`, `result.columns`, `retry.count`
> - `t3`: `validation.passed`, `validation.check_count`
> - `t4`: `response.confidence`, `response.table_count`, `response.artifact_count`
>
> Important constraints:
>
> - Preserve existing `TraceStep` payloads exactly.
> - Preserve `LlmTraceCollector` behavior.
> - Use manual spans around stage boundaries (do not rely only on SDK auto-instrumentation).
> - Ensure async context propagation.
>
> After implementation, provide verification steps for:
>
> - existing UI trace still intact
> - Phoenix spans visible and populated

---

## Prompt 2: Tier 1 Inline Checks (Deterministic, Hot Path)

> Implement Tier 1 inline checks for `t1..t4`.
>
> Create `apps/orchestrator/app/evaluation/inline_checks_v2_1.py` with exact signatures:
>
> ```python
> def check_plan_sanity(plan: list[dict[str, object]], *, max_steps: int = 5) -> tuple[bool, str]: ...
> def check_sql_syntax(sql: str) -> tuple[bool, str]: ...
> def check_result_sanity(rows: list[dict[str, object]], row_count: int, *, max_rows: int, max_cell_bytes: int = 1_000_000) -> tuple[bool, str]: ...
> def check_validation_contract(passed: bool, checks: list[str]) -> tuple[bool, str]: ...
> def check_answer_sanity(answer: str, *, min_chars: int = 20) -> tuple[bool, str]: ...
> def check_pii(answer: str) -> tuple[bool, str]: ...
> def redact_pii(answer: str) -> str: ...
> ```
>
> Requirements:
>
> - use `sqlparse` for syntax validation (`SELECT` or `WITH`)
> - add regex checks for SSN/account/card-like patterns
> - keep checks lightweight
>
> Integration:
>
> - run each check after corresponding stage
> - record outcomes in:
>   - UI trace (`qualityChecks` or `stageOutput`)
>   - Phoenix span events
> - on failed synthesis PII check, redact answer and append warning assumption
>
> Do not alter existing stage business logic flow beyond check hooks and fallback/redaction.

---

## Prompt 3: Golden Dataset v2.1

> Build Phoenix-ready golden dataset assets while preserving legacy eval harness dataset.
>
> Create:
>
> - `evaluation/golden_dataset_v2_1.py`
> - `evaluation/golden_examples_v2_1.yaml`
> - `evaluation/upload_golden_dataset_v2_1.py`
>
> Golden example schema:
>
> - `input`
> - `expected_plan`
> - `expected_sql_steps`
> - `expected_answer`
> - `difficulty` (`simple|moderate|complex`)
> - `must_contain`
> - `category`
>
> Dataset composition target:
>
> - 4 simple
> - 4 moderate
> - 2 complex
>
> Use real semantic model entities and actual table/column vocabulary.
>
> Upload dataset name:
>
> - `cortex-analyst-golden-v2-1`

---

## Prompt 4: Tier 3 Deterministic Evaluators

> Create deterministic evaluators in `evaluation/code_evaluators_v2_1.py`.
>
> Use Phoenix code evaluator decorators and implement:
>
> 1. `execution_accuracy(output, expected) -> float`
>    - compare generated SQL step results vs expected SQL step results
>    - support multi-step (`sql_steps` list)
>    - use `datacompy` for DataFrame comparison
>    - robust error handling (`return 0.0` on failure)
>
> 2. `decomposition_coverage(output, expected) -> float`
>    - normalized token/topic overlap between produced plan and expected plan
>
> 3. `key_value_presence(output, expected) -> float`
>    - `must_contain` hit fraction in final answer
>
> 4. `sql_syntax_valid(output) -> float`
>    - fraction of generated SQL steps passing syntax check
>
> Requirements:
>
> - deterministic, side-effect free
> - resilient to missing keys
> - no uncaught exceptions

---

## Prompt 5: Tier 3 LLM Evaluators + Experiment Runner

> Create LLM evaluator configuration and experiment runner.
>
> Create:
>
> - `evaluation/llm_evaluators_v2_1.py`
> - `evaluation/run_experiment_v2_1.py`
>
> Configure Phoenix templates:
>
> - `SQL_GEN_EVAL_PROMPT_TEMPLATE`
> - `HALLUCINATION_PROMPT_TEMPLATE`
> - `QA_PROMPT_TEMPLATE`
> - `SUMMARIZATION_PROMPT_TEMPLATE` (adapted for synthesis quality if needed)
>
> Custom classifier:
>
> - name: `decomposition_quality`
> - choices: `{"complete": 1.0, "partial": 0.5, "poor": 0.0}`
> - prompt asks coverage/redundancy/off-topic quality for `t1` plan
>
> `pipeline_task` requirements:
>
> - run full orchestrator turn for each question
> - normalize outputs to:
>   - `plan_steps`
>   - `sql_steps`
>   - `sql_results_summary`
>   - `validation`
>   - `final_answer`
>   - `synthesis_context`
>
> CLI:
>
> - `python evaluation/run_experiment_v2_1.py --name "<name>" --description "<desc>"`

---

## Prompt 6: Tier 2 Async Production Eval (Detailed)

> Create `evaluation/async_production_eval_v2_1.py`.
>
> Implement:
>
> 1. Pull spans:
>    - `client.get_spans_dataframe(project_name="cortex-analyst-pipeline", start_time=...)`
>
> 2. Build evaluator dataframes by stage:
>    - `t1_plan` -> decomposition quality inputs
>    - `t2_sql` -> SQL eval inputs (`question`, `query_gen`, `response`)
>    - `t4_synthesis` -> hallucination/QA inputs
>
> 3. Run evals with:
>    - `llm_classify(..., concurrency=20, provide_explanation=True)`
>
> 4. Log:
>    - `client.log_evaluations(SpanEvaluations(...))`
>
> 5. Flag and export:
>    - hallucinated
>    - SQL incorrect
>    - QA incorrect
>    - `evaluation/flagged/review_YYYYMMDD.csv`
>
> 6. CLI:
>    - `python evaluation/async_production_eval_v2_1.py --hours 1`
>
> Critical context note in code comments:
>
> - Tier 2 has no ground truth; reference/context must come from pipeline outputs only.

---

## Prompt 7: CI/CD Quality Gate (Phoenix Authoritative + Legacy Advisory)

> Create:
>
> - `.github/workflows/eval_v2_1.yml`
> - `evaluation/quality_gate_v2_1.py`
>
> Workflow triggers:
>
> - PR changes in:
>   - `apps/orchestrator/**`
>   - `evaluation/**`
>   - `apps/orchestrator/app/prompts/**`
>   - `packages/semantic-model/**`
> - nightly schedule at 2am
>
> Steps:
>
> 1. setup Python and Node
> 2. install orchestrator + eval dependencies
> 3. run `run_experiment_v2_1.py`
> 4. run `quality_gate_v2_1.py` (blocking)
> 5. optionally run legacy `npm run eval` (non-blocking advisory artifact)
>
> Gate thresholds:
>
> - execution_accuracy >= 0.80
> - decomposition_coverage >= 0.75
> - key_value_presence >= 0.85
> - sql_syntax_valid >= 0.95
> - SQL Correctness >= 0.80
> - Hallucination >= 0.85
> - QA Correctness >= 0.80
> - Summarization >= 0.80
>
> Required secrets/environment variables:
>
> - `PHOENIX_API_KEY`
> - `PHOENIX_COLLECTOR_ENDPOINT`
> - Azure/OpenAI judge credentials
> - SQL execution credentials used by evaluator execution path

---

## Prompt 8: Eval-the-Evals v2.1

> Create:
>
> - `evaluation/eval_the_evals_v2_1.py`
> - `evaluation/annotation_guide_v2_1.md`
>
> Script requirements:
>
> - pull traces with both LLM eval labels and human labels
> - compute agreement percentage and Cohen's kappa per evaluator
> - flag evaluators under 0.80 agreement
> - export calibration report
>
> Guide requirements:
>
> - weekly flagged-trace review process
> - annotation conventions (`correct|partial|incorrect` by stage)
> - monthly calibration runbook
> - failure promotion path into golden dataset

---

## Expected v2.1 File Tree

```text
evaluation/
├── inline_checks_v2_1.py
├── golden_dataset_v2_1.py
├── golden_examples_v2_1.yaml
├── upload_golden_dataset_v2_1.py
├── code_evaluators_v2_1.py
├── llm_evaluators_v2_1.py
├── async_production_eval_v2_1.py
├── run_experiment_v2_1.py
├── quality_gate_v2_1.py
├── eval_the_evals_v2_1.py
├── annotation_guide_v2_1.md
├── flagged/
│   └── .gitkeep
apps/orchestrator/app/
└── tracing.py
docs/
└── eval_code_mapping_v2_1.md
.github/workflows/
└── eval_v2_1.yml
```

Legacy retained:

- `packages/eval-harness/**`
- `npm run eval`

---

## Verification Checklist (Restored Detail)

1. Start orchestrator and run one request:
   - verify UI trace unchanged
   - verify Phoenix spans for `t1..t4`
2. Trigger Tier 1 inline check failures:
   - malformed SQL check behavior
   - synthesis PII redaction behavior
3. Upload golden v2.1 dataset:
   - verify in Phoenix datasets
4. Run Tier 3 experiment:
   - verify deterministic + LLM scores
5. Run Tier 2 async eval:
   - verify span annotations and flagged CSV
6. Open PR touching prompts or orchestrator:
   - verify Phoenix quality gate blocks on threshold failure
   - verify legacy eval runs as advisory signal

