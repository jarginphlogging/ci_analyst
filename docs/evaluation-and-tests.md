# Evaluation and Tests

## Included

- Orchestrator unit + route tests (`pytest`)
- Real orchestration dependency tests with stubbed LLM/SQL providers (`pytest`)
- SQL guardrail tests for allowlist and row-limit enforcement (`pytest`)
- Frontend stream parser tests (`vitest`)
- Eval harness with golden dataset and answer-token matching

## Commands

```bash
npm run test
npm run eval
```

## Eval Harness

- Dataset: `/Users/joe/Code/ci_analyst/packages/eval-harness/datasets/golden-v1.json`
- Runner: `/Users/joe/Code/ci_analyst/packages/eval-harness/src/run-eval.mjs`

Override base URL:
```bash
EVAL_BASE_URL=http://localhost:8787 npm run eval
```

## Extending Evaluation

1. Add golden questions covering multi-turn and ambiguity.
2. Add strict numeric checks by expected metric payload.
3. Track latency p50/p95 and enforce regression thresholds in CI.
