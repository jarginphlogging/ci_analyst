# Evaluations

Use this file for benchmark, golden-dataset, and eval workflow guidance plus result interpretation.

## Purpose

This document explains how evaluation, benchmark, and golden-dataset workflows work in this repository.

It should help answer:
- where eval data lives
- how evals are run
- what counts as a regression
- how to interpret results
- when evals are required

---

## Evaluation philosophy

Use evals when changes may affect:
- answer correctness
- groundedness
- output quality
- SQL/query generation quality
- orchestration behavior
- reasoning or summarization behavior
- user-visible trustworthiness

Prefer:
- fast relevant subset first
- expected-vs-actual comparison
- concise pass/fail summary
- failure clustering
- clear distinction between real regressions and harness/environment issues

Do not:
- skip evals when logic quality clearly changed
- hand-wave regressions away
- conflate harness breakage with product regressions

Repo-specific guidance:
- prompt changes are behavioral changes and should be treated as eval-relevant
- deterministic checks are preferred before judge-based quality scoring
- compare against known-good examples before claiming an improvement

---

## Eval assets

### `packages/eval-harness/src/run-eval.mjs`
- Role: fast local eval runner against `/v1/chat/turn`
- Inputs:
  - `EVAL_BASE_URL`
  - `EVAL_DATASET_PATH`
  - dataset cases from `packages/eval-harness/datasets/golden-v1.json` by default
- Outputs:
  - JSON summary printed to stdout
  - non-zero exit code on failing cases
- Notes:
  - this is the canonical fast local eval path
  - scoring includes token matches, numeric assertions, and latency

### `packages/eval-harness/src/score.mjs`
- Role: scoring logic for the fast local harness
- Inputs:
  - eval payloads
  - required token expectations
  - numeric assertions
- Outputs:
  - pass/fail scoring inputs used by the harness summary
- Notes:
  - this is the main place to inspect when a harness verdict looks surprising

### `packages/eval-harness/datasets/golden-v1.json`
- Role: default fast local dataset
- Inputs:
  - question text
  - token expectations
  - numeric assertions
  - latency thresholds
- Outputs:
  - cases consumed by `run-eval.mjs`
- Notes:
  - despite the filename, this is a product eval dataset, not a semantic-model artifact
  - supported case fields include `id`, `question`, `mustContainAny`, optional `minTokenHits`, optional `maxLatencyMs`, and optional `numericAssertions`

### `evaluation/golden_examples_v2_1.yaml`
- Role: canonical YAML golden dataset for the broader Python/Phoenix eval stack
- Inputs:
  - curated examples and expected outputs
- Outputs:
  - dataset records via `evaluation/golden_dataset_v2_1.py`
- Notes:
  - this is the repo’s broader golden dataset source for the v2.1 Python eval flow

### `evaluation/golden_dataset_v2_1.py`
- Role: load and normalize the YAML golden dataset
- Inputs:
  - optional `--dataset-path`
  - `evaluation/golden_examples_v2_1.yaml` by default
- Outputs:
  - dataset records suitable for upload or experiment runs
- Notes:
  - this is the fallback path used when the Phoenix dataset is not already present

### `evaluation/run_experiment_v2_1.py`
- Role: broader Phoenix-backed experiment runner
- Inputs:
  - `--name`
  - `--description`
  - `--dataset`
  - optional `--dataset-path`
- Outputs:
  - experiment results in Phoenix
  - logged decomposition, SQL, hallucination, QA, and synthesis evals
- Notes:
  - uses both code evaluators and judge-backed evaluators
  - `python -m evaluation.*` entrypoints auto-load `apps/orchestrator/.env`

### `evaluation/quality_gate_v2_1.py`
- Role: result-summary and gate decision for Phoenix experiment metrics
- Inputs:
  - optional `--experiment-name`
  - logged Phoenix evaluation data
- Outputs:
  - PASS/FAIL summary per metric
  - non-zero exit code if thresholds fail
- Notes:
  - this is the closest thing to a canonical result-summary command in the broader eval stack

### `evaluation/eval_the_evals_v2_1.py`
- Role: calibration report for judge agreement quality
- Inputs:
  - annotation/review data
  - `--min-agreement`
- Outputs:
  - evaluator agreement report
- Notes:
  - use when the evaluator quality itself is in doubt

### `evaluation/async_production_eval_v2_1.py`
- Role: async production-style Phoenix eval workflow
- Inputs:
  - recent production traces
  - `--hours`
- Outputs:
  - logged trace-level evals
- Notes:
  - broader and heavier than the local harness; not the default first step for normal feature work

---

## Eval commands

### Primary eval command
- `npm run eval`

### Fast subset command
- No dedicated subset script is currently wired.
- Practical subset path for the fast harness: point `EVAL_DATASET_PATH` at a smaller JSON dataset file.
- Example:

```bash
EVAL_DATASET_PATH=/absolute/path/to/subset.json npm run eval
```

### Result summary command
- `python -m evaluation.quality_gate_v2_1 --experiment-name "local-v2.1"`

Additional repo-backed commands:

```bash
EVAL_BASE_URL=http://localhost:8787 npm run eval
python -m evaluation.upload_golden_dataset_v2_1 --name cortex-analyst-golden-v2-1
python -m evaluation.run_experiment_v2_1 --name "local-v2.1" --description "local eval run"
python -m evaluation.eval_the_evals_v2_1 --min-agreement 0.80
python -m evaluation.async_production_eval_v2_1 --hours 1
```

If these commands are not obvious, inspect scripts/configs rather than inventing them.

Uncertainty:
- This machine did not expose a working `python` executable during this pass, so the Python commands were confirmed from repo code and package scripts rather than from `--help` output.

Judge-provider environment notes:

```bash
# OpenAI (default)
EVAL_JUDGE_PROVIDER=openai
EVAL_JUDGE_MODEL=gpt-4o-mini
OPENAI_API_KEY=...

# Azure OpenAI
EVAL_JUDGE_PROVIDER=azure   # aliases: azureopenai, azure_openai, azure-openai
EVAL_JUDGE_MODEL=<azure_deployment_name>
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-10-21

# Anthropic
EVAL_JUDGE_PROVIDER=anthropic
EVAL_JUDGE_MODEL=claude-3-5-sonnet-latest
ANTHROPIC_API_KEY=...
```

Advanced passthrough exists for provider-specific client kwargs:

```bash
EVAL_JUDGE_CLIENT_KWARGS_JSON='{"base_url":"https://...","timeout":60}'
EVAL_JUDGE_SYNC_CLIENT_KWARGS_JSON='{"timeout":60}'
EVAL_JUDGE_ASYNC_CLIENT_KWARGS_JSON='{"timeout":120}'
```

If the selected provider SDK is missing, evaluator startup should fail fast.

---

## When to run evals

Run evals when:
- changing prompt or orchestration logic
- changing SQL/query generation behavior
- changing answer synthesis / insight generation
- modifying ranking, grounding, or retrieval logic
- altering logic that affects expected outputs

Start with:
- the smallest relevant subset
- the most representative examples
- the highest-value or most failure-prone cases

Escalate to broader evals if:
- failures cluster
- the changed logic is broad
- the risk is high

Practical repo order:
1. fast local harness with `npm run eval`
2. smaller custom subset via `EVAL_DATASET_PATH` when narrowing diagnosis
3. broader Phoenix experiment run for deeper quality evaluation
4. quality gate after a Phoenix-backed experiment

Phoenix v2.1 role in the broader eval stack:
- runtime inline checks on orchestrator stages
- async production LLM-as-judge scoring for decomposition, SQL correctness, hallucination, and synthesis quality
- Tier 2 intentionally excludes QA correctness scoring because production traces do not carry ground-truth reference answers
- Tier 3 golden dataset experiments
- quality gate as the release-decision surface

---

## Failure classification

Classify results into at least these categories:

### Hard regression
Behavior is clearly worse or incorrect relative to expected output.

### Soft quality drop
Behavior is still acceptable or partly correct but measurably worse.

### Harness issue
The eval machinery, dataset, or comparison logic is broken or inconsistent.

### Environment issue
A setup/runtime/dependency issue interfered with the eval result.

### Unclear / needs inspection
Not enough evidence yet to classify.

Repo-specific hints:
- HTTP failures from `run-eval.mjs` often point to app availability or environment issues before they prove answer-quality regressions.
- Missing Phoenix metrics usually indicate setup/data availability issues before they prove product regressions.

---

## Reporting expectations

A good eval summary should state:
- what was evaluated
- what subset was run
- pass/fail status
- notable deltas
- clustered failure themes
- likely causes if visible
- whether failures look real vs harness/environment related

Keep summaries concise and decision-oriented.

---

## Update rule

Update this doc when:
- the eval harness changes
- a new benchmark set becomes important
- the scoring method changes
- the canonical eval workflow changes
