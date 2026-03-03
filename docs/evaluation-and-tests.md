# Evaluation and Tests

## Included

- Orchestrator unit + route tests (`pytest`)
- Real orchestration dependency tests with stubbed LLM/SQL providers (`pytest`)
- SQL guardrail tests for allowlist and row-limit enforcement (`pytest`)
- Frontend stream parser tests (`vitest`)
- Eval harness with golden dataset, token checks, numeric assertions, route checks, and latency gates

## Commands

```bash
npm run test
npm run eval
```

Phoenix eval stack (v2.1):

```bash
python -m pip install -r requirements-eval.txt
python -m evaluation.upload_golden_dataset_v2_1 --name cortex-analyst-golden-v2-1
python -m evaluation.run_experiment_v2_1 --name "local-v2.1" --description "local eval run"
python -m evaluation.async_production_eval_v2_1 --hours 1
python -m evaluation.quality_gate_v2_1 --experiment-name "local-v2.1"
python -m evaluation.eval_the_evals_v2_1 --min-agreement 0.80
```

## Eval Harness

- Dataset: `/Users/joe/Code/ci_analyst/packages/eval-harness/datasets/golden-v1.json`
- Runner: `/Users/joe/Code/ci_analyst/packages/eval-harness/src/run-eval.mjs`
- Role: fast advisory feedback loop (non-authoritative)

Phoenix v2.1 role:

- Runtime inline checks on `t1..t4` stages
- Async production LLM-as-judge scoring
- Tier 3 golden dataset experiments
- Authoritative quality gate for release decisions

Override base URL:
```bash
EVAL_BASE_URL=http://localhost:8787 npm run eval
```

Optional runtime controls:
```bash
EVAL_DATASET_PATH=/absolute/path/to/dataset.json
EVAL_FAST_PATH_P50_MAX_MS=2500
EVAL_FAST_PATH_P95_MAX_MS=5000
EVAL_DEEP_PATH_P50_MAX_MS=7000
EVAL_DEEP_PATH_P95_MAX_MS=15000
```

Dataset fields supported per case:
- `id`
- `question`
- `mustContainAny` (string[])
- `minTokenHits` (number, optional, default `1`)
- `expectedRoute` (`fast_path|deep_path`, optional)
- `maxLatencyMs` (number, optional)
- `numericAssertions` (optional array of `{label, field(value|delta), expected, tolerance, unit?}`)

## Extending Evaluation

1. Add golden questions covering multi-turn and ambiguity.
2. Add route expectations and per-case numeric assertions for critical KPIs.
3. Tighten route-specific latency budgets over time and enforce in CI.
