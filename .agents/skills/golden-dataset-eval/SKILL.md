---
name: golden-dataset-eval
description: Use for golden dataset checks, benchmark runs, expected-vs-actual comparisons, regression evaluation, and accuracy checks after code, prompt, orchestration, or logic changes. Best for targeted eval subsets, failure clustering, and concise decision-oriented summaries. Trigger phrases include: run the golden dataset, benchmark this change, eval regression, compare expected vs actual, accuracy check, run the eval harness.
---

# Golden Dataset Eval

## Purpose

Use this skill for known-good examples, benchmark workflows, and regression evaluation.

This skill is for quality/regression checks, not generic product/browser testing.

---

## Use when

Use this skill when:
- logic quality may have changed
- prompt/orchestration behavior changed
- expected-vs-actual comparison is needed
- a benchmark or eval harness should be run
- answer quality or correctness needs regression checking

Repo-specific examples:
- running `npm run eval` after planner, SQL, synthesis, or prompt changes
- checking whether a branch regressed on `packages/eval-harness/datasets/golden-v1.json`
- running the broader Phoenix-backed eval flow after higher-risk orchestration changes
- comparing actual versus expected outputs after changes that may affect groundedness or answer quality

---

## Do not use when

Do not use this skill when:
- the main need is browser/UI/product flow validation
- the task is generic feature implementation
- the task is generic code review

Use `playwright-product-test` for browser-visible behavior.
Use `feature-implementation` for building.
Use `pr-review` for reviewing diffs.

---

## Workflow

1. Locate the golden dataset, benchmark assets, and eval harness.
2. Infer the existing eval workflow from the repo.
3. Start with the smallest relevant subset first.
4. Compare actual vs expected outputs.
5. Classify failures into:
   - hard regression
   - soft quality drop
   - harness issue
   - environment issue
   - unclear / needs inspection
6. Cluster related failures.
7. Summarize:
   - what was run
   - pass/fail status
   - notable deltas
   - likely causes where visible
   - recommendation / next step

Repo-specific workflow notes:
- the canonical fast local path is `npm run eval`
- there is no dedicated built-in subset flag, so a smaller dataset is typically supplied through `EVAL_DATASET_PATH`
- broader eval work lives under `evaluation/` and includes `run_experiment_v2_1.py` and `quality_gate_v2_1.py`
- judge-backed Phoenix results should be separated from deterministic harness checks when summarizing confidence

---

## Validation / completion criteria

A good eval result should include:
- the dataset/subset used
- the command or harness path used
- pass/fail summary
- notable regressions
- clustered failure themes
- distinction between real regressions and harness/environment issues

Do not treat a broken harness as a product regression.

Repo-specific completion examples:
- identify whether the run used `npm run eval`, a subset dataset via `EVAL_DATASET_PATH`, or a Python/Phoenix experiment
- note whether failures came from token checks, numeric assertions, latency, or judge/code evaluators
- separate app failures from service-availability or Phoenix-environment problems

---

## Examples

Good triggers:
- “Run the golden dataset after this change.”
- “Evaluate this logic change on the benchmark subset.”
- “Compare expected vs actual outputs and summarize regressions.”
- “Run the eval harness and cluster failures.”
- “Tell me whether this branch still passes the fast eval path.”

Bad triggers:
- “Run Playwright on the main UI.”
- “Implement this feature.”
- “Review this PR.”

---

## Troubleshooting

### Eval harness is unclear
Inspect scripts/configs/docs first instead of guessing.

### Too many failures
Cluster them before reporting. Do not dump an unstructured wall of failures.

### Results are ambiguous
Say so explicitly and separate:
- likely real regression
- likely harness problem
- likely environment/setup issue

### The broader Python stack is blocked
Use the fast local harness first, then state what deeper Phoenix-backed checks remain unverified.

---

## Trigger tests

### Should trigger

1. Run the golden dataset and tell me what regressed.
2. Execute the eval harness for this branch.
3. Summarize the quality-gate failures after this change.
4. Compare actual versus expected outputs for the failing golden cases.
5. Run a quick relevant eval subset for the synthesis update.
6. Check whether the planner refactor broke golden examples.
7. Execute the repo's eval workflow and cluster the failures.
8. Inspect whether the latency assertions still pass.
9. Distinguish product regressions from harness issues in these eval results.
10. Tell me if this branch passes the eval harness.

### Should not trigger

1. Use Playwright to test the export flow in the browser.
2. Review this diff for fallback creep and missing tests.
3. Investigate why the sandbox service will not start locally.
4. Research the best way to add a new evaluation field before coding.
5. Implement the approved fix for the planner regression.

## Overlap risks and metadata improvements

- Some “test this” prompts overlap with `playwright-product-test`; keeping "golden dataset", "benchmark", and "eval harness" explicit helps.
- Regression-investigation requests overlap with `bug-triage`; this skill should trigger when running or interpreting the eval workflow is central.
- Requests that ask for both running evals and fixing failures may need this skill first and `feature-implementation` second.
