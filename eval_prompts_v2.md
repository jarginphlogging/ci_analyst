# Claude Code Prompts v2 — Evaluation Pipeline Implementation (Code-Aligned)

## Usage

These prompts are sequential and preserve the original evaluation intent.  
They are adapted to this repository's real orchestrator contracts:

- `t1` plan
- `t2` SQL generation + execution
- `t3` validation
- `t4` synthesis

Do not modify existing `eval_plan.md` or `eval_prompts.md`.  
Use this v2 file as the implementation sequence.

---

## Prompt 0: Orientation + Contract Mapping

> Read `eval_plan_v2.md` and the current orchestrator pipeline code.  
> Produce `docs/eval_code_mapping_v2.md` with:
>
> 1. Exact mapping of `t1..t4` to file/function boundaries
> 2. Input/output payload contracts for each stage (real types and field names)
> 3. Existing tracing payloads (UI trace + LLM trace collector)
> 4. Where Phoenix tracing hooks should be added with minimum duplication
> 5. Current SQL provider wiring and where evaluator execution should integrate
>
> Do not change code yet.

---

## Prompt 1: Dual Tracing (Keep Existing + Add Phoenix)

> Implement Phoenix tracing in parallel with current trace output.
>
> Requirements:
>
> - Keep existing UI trace payloads unchanged (`TraceStep`, `stageInput`, `stageOutput`).
> - Add Phoenix/OTel tracing as a second sink for `t1..t4`.
> - Ensure SQL generation/execution attempt metadata is captured on `t2`.
> - Ensure tracing initialization runs once.
> - Preserve async context propagation.
>
> Notes:
>
> - Do not remove or refactor away `LlmTraceCollector`.
> - Do not rely solely on OpenAI SDK instrumentation because current providers use custom HTTP adapters.
> - Prefer manual stage spans plus structured attributes.
>
> Deliverables:
>
> - tracing setup module(s)
> - stage instrumentation code changes
> - verification instructions for both UI trace and Phoenix spans

---

## Prompt 2: Tier 1 Inline Checks (t1..t4)

> Implement Tier 1 inline checks aligned to current stages and integrate into hot path.
>
> Add deterministic checks for:
>
> - `t1`: plan structure sanity (count bounds, task shape)
> - `t2`: SQL/output payload sanity beyond existing guardrails where needed
> - `t3`: validation output contract sanity
> - `t4`: output sanity + PII detection/redaction
>
> Integration requirements:
>
> - Checks run after corresponding stage completion.
> - Fail behavior respects current block/retry/fallback semantics.
> - Check outcomes are logged to both UI trace and Phoenix span events/attributes.
> - Keep added latency lightweight.

---

## Prompt 3: Golden Dataset v2 (Phoenix-Compatible)

> Build golden dataset infrastructure for Tier 3 without removing legacy dataset usage.
>
> Create:
>
> - `evaluation/golden_dataset_v2.py`
> - `evaluation/golden_examples_v2.yaml`
> - `evaluation/upload_golden_dataset_v2.py`
>
> Dataset schema should support current pipeline outputs:
>
> - `input` (question)
> - `expected_plan` (expected `t1` task decomposition)
> - `expected_sql_steps` (expected SQL per logical step or canonical equivalent)
> - `expected_answer`
> - `must_contain`
> - `difficulty`
> - `category`
>
> Constraints:
>
> - Use actual semantic model entities and available tables.
> - Keep legacy eval harness dataset untouched.
> - Upload as Phoenix dataset `cortex-analyst-golden-v2`.

---

## Prompt 4: Tier 3 Deterministic Code Evaluators (v2)

> Create deterministic evaluators for `t1..t4` correctness scoring.
>
> Create `evaluation/code_evaluators_v2.py` with evaluators such as:
>
> - `execution_accuracy` (generated vs expected SQL result equivalence)
> - `decomposition_coverage` (actual vs expected plan coverage)
> - `key_value_presence` (must-contain values in final answer)
> - `sql_syntax_valid` (syntax/policy validity score)
>
> Requirements:
>
> - Handle multi-step SQL output from `t2`.
> - Handle execution errors gracefully; never crash experiment.
> - Reuse configured SQL execution pathway pattern for deterministic checks.

---

## Prompt 5: Tier 3 LLM Evaluators + Experiment Runner (v2)

> Create LLM evaluator configuration and experiment runner aligned to `t1..t4`.
>
> Create:
>
> - `evaluation/llm_evaluators_v2.py`
> - `evaluation/run_experiment_v2.py`
>
> Configure evaluators for:
>
> - Plan/decomposition quality (`t1`)
> - SQL correctness (`t2`)
> - Hallucination/grounding (`t4`)
> - QA correctness (`t4`)
> - Synthesis quality (`t4`)
>
> Critical:
>
> - Tier 3 LLM evals must include ground-truth reference from golden dataset.
> - Experiment task must run full pipeline and emit normalized outputs for evaluators.
>
> CLI:
>
> `python evaluation/run_experiment_v2.py --name "<version>" --description "<change summary>"`

---

## Prompt 6: Tier 2 Async Production Evals (v2)

> Build async production evaluation pipeline using Phoenix traces/spans.
>
> Create `evaluation/async_production_eval_v2.py` that:
>
> 1. Pulls recent traces/spans for configurable time window.
> 2. Builds evaluator DataFrames mapped to `t1..t4` contracts.
> 3. Runs LLM evals (plan quality, SQL quality, hallucination, QA).
> 4. Logs scores back to Phoenix.
> 5. Writes flagged traces to `evaluation/flagged/review_YYYYMMDD.csv`.
>
> Tier 2 context rule:
>
> - No ground truth.
> - Judge references pipeline-produced context only.
> - Document this clearly in code comments.

---

## Prompt 7: CI/CD Quality Gate (Phoenix Authoritative)

> Create Phoenix-authoritative quality gate while preserving legacy fast eval loop.
>
> Create:
>
> - `.github/workflows/eval_v2.yml`
> - `evaluation/quality_gate_v2.py`
>
> Behavior:
>
> - Run Tier 3 experiment (`run_experiment_v2.py`).
> - Evaluate thresholds and fail CI on Phoenix metric regression.
> - Optionally run legacy eval harness as advisory (non-blocking) signal.
>
> Explicit policy:
>
> - Phoenix gate is release authority.
> - Legacy eval remains quick feedback loop only.

---

## Prompt 8: Eval-the-Evals v2

> Implement judge calibration workflow for v2 evaluators.
>
> Create:
>
> - `evaluation/eval_the_evals_v2.py`
> - `evaluation/annotation_guide_v2.md`
>
> Requirements:
>
> - compare human labels vs LLM judge labels
> - report agreement and kappa per evaluator
> - flag low-agreement evaluators for tuning
> - define lightweight weekly review and monthly calibration process

---

## Expected v2 Deliverables

```text
evaluation/
├── golden_dataset_v2.py
├── golden_examples_v2.yaml
├── upload_golden_dataset_v2.py
├── code_evaluators_v2.py
├── llm_evaluators_v2.py
├── async_production_eval_v2.py
├── run_experiment_v2.py
├── quality_gate_v2.py
├── eval_the_evals_v2.py
├── annotation_guide_v2.md
├── flagged/
│   └── .gitkeep
docs/
├── eval_code_mapping_v2.md
.github/workflows/
└── eval_v2.yml
```

Legacy assets remain intact:

- `packages/eval-harness/**`
- existing `npm run eval` workflow

---

## Verification Sequence

1. Run one request and confirm both UI trace and Phoenix spans for `t1..t4`.
2. Trigger an inline check violation and verify correct fail/fallback behavior.
3. Upload golden v2 dataset and confirm visibility in Phoenix.
4. Run `run_experiment_v2.py` and verify evaluator outputs.
5. Run `async_production_eval_v2.py` and verify span/trace annotations.
6. Run CI workflow and confirm Phoenix threshold gate behavior.
7. Confirm legacy eval still executes quickly as advisory feedback.

