# Evaluation and Tests

## Included

- Orchestrator unit + route tests (`pytest`)
- Real orchestration dependency tests with stubbed LLM/SQL providers (`pytest`)
- SQL guardrail tests for allowlist and row-limit enforcement (`pytest`)
- Frontend stream parser tests (`vitest`)
- Eval harness with golden dataset, token checks, numeric assertions, and latency gates

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

Environment loading:

- All `python -m evaluation.*` entrypoints auto-load `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`.
- Keep Phoenix + judge provider credentials in that single backend env file.

Phoenix judge provider configuration (for LLM-as-judge evaluators):

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

Advanced passthrough for provider-specific client kwargs:

```bash
EVAL_JUDGE_CLIENT_KWARGS_JSON='{"base_url":"https://...","timeout":60}'
EVAL_JUDGE_SYNC_CLIENT_KWARGS_JSON='{"timeout":60}'
EVAL_JUDGE_ASYNC_CLIENT_KWARGS_JSON='{"timeout":120}'
```

If the selected provider SDK is missing, evaluator startup will fail fast with the Phoenix provider availability table.

## Eval Harness

- Dataset: `/Users/joe/Code/ci_analyst/packages/eval-harness/datasets/golden-v1.json`
- Runner: `/Users/joe/Code/ci_analyst/packages/eval-harness/src/run-eval.mjs`
- Role: fast advisory feedback loop (non-authoritative)

Phoenix v2.1 role:

- Runtime inline checks on `t1..t4` stages
- Async production LLM-as-judge scoring (decomposition, SQL correctness, hallucination, synthesis quality)
- Tier 2 intentionally excludes QA correctness scoring because production traces lack ground-truth reference answers
- Tier 3 golden dataset experiments
- Authoritative quality gate for release decisions

Override base URL:
```bash
EVAL_BASE_URL=http://localhost:8787 npm run eval
```

Optional runtime controls:
```bash
EVAL_DATASET_PATH=/absolute/path/to/dataset.json
```

Dataset fields supported per case:
- `id`
- `question`
- `mustContainAny` (string[])
- `minTokenHits` (number, optional, default `1`)
- `maxLatencyMs` (number, optional)
- `numericAssertions` (optional array of `{label, field(value|delta), expected, tolerance, unit?}`)

## Extending Evaluation

1. Add golden questions covering multi-turn and ambiguity.
2. Add per-case numeric assertions for critical KPIs.
3. Tighten per-case latency budgets over time and enforce in CI.
