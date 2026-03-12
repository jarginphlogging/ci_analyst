---
name: bug-triage
description: Use for reproducing, isolating, diagnosing, and fixing defects, regressions, broken flows, or unexpected behavior. Best for neutral investigation, likely-cause ranking, targeted fixes, and distinguishing app failures from environment or flaky failures. Trigger phrases include: debug this, triage this bug, investigate this regression, broken flow, why is this failing, reproduce this issue.
---

# Bug Triage

## Purpose

Use this skill to investigate and resolve bugs or regressions.

This skill is designed to reduce biased debugging and low-quality "fixes."
It should investigate neutrally and report findings clearly.

---

## Use when

Use this skill when:
- a bug is reported
- a regression is suspected
- a user flow is broken
- behavior is unexpected
- a failure needs reproduction or isolation
- the root cause is not yet clear

Repo-specific examples:
- streamed chat stalls or hydrates incorrectly
- an orchestrator stage appears to violate planner/SQL/validation/synthesis boundaries
- `npm run eval` or the Phoenix quality gate fails and the cause is unclear
- a user-visible flow regresses in the web app

---

## Do not use when

Do not use this skill when:
- the main need is implementing a clearly defined feature
- the main need is reviewing a diff
- the main need is researching framework/library options

Use `feature-implementation` when the implementation direction is already chosen.
Use `pr-review` when the task is review-only.
Use `docs-research` when the main need is approach selection.

---

## Investigation rule

Prefer neutral framing:
- inspect and report findings
- trace the flow
- identify anomalies
- rank likely causes

Do not assume a bug exists in a specific place unless evidence supports it.

---

## Workflow

1. Restate the observed issue clearly.
2. Reproduce or isolate the issue if possible.
3. Inspect the relevant execution path.
4. Compare expected vs actual behavior.
5. Gather evidence:
   - logs
   - errors
   - failing tests
   - visible state
   - console/network signals if relevant
6. Rank likely causes.
7. Distinguish:
   - real app bug
   - test failure
   - environment/setup issue
   - flaky issue
8. Apply the smallest credible fix if appropriate.
9. Validate with targeted checks.
10. Summarize:
   - issue
   - evidence
   - likely cause
   - fix
   - validation
   - remaining uncertainty

Repo-specific investigation reminders:
- check whether the failure is in the web proxy, orchestrator, stage logic, eval harness, or environment before changing code
- for user-facing regressions, inspect visible state, console errors, and important network failures together
- if semantic meaning looks wrong, inspect the YAML-driven path before patching downstream logic

---

## Anti-fallback check

Do not "fix" bugs by adding fallback glue, compatibility shims, silent degradation, or dual old/new paths unless explicitly requested.

Prefer:
- finding the real cause
- preserving one canonical path
- failing explicitly rather than hiding the failure

---

## Validation / completion criteria

A bug triage task is not complete unless:
- the issue was reproduced or meaningfully isolated
- evidence supports the likely cause
- the fix was validated with the most relevant targeted checks
- residual uncertainty is stated clearly if the root cause is not fully confirmed

Repo-specific validation examples:
- use targeted workspace tests for stage, contract, or frontend failures
- use focused Playwright or product-flow checks for visible regressions
- use `npm run eval` first when prompt, orchestration, SQL, or synthesis behavior may have regressed
- distinguish app failures from harness, environment, and flaky failures in the final report

---

## Examples

Good triggers:
- “Triage this regression in the results panel.”
- “Investigate why this flow is failing after the last change.”
- “Reproduce and diagnose this console/network error.”
- “Why is this test suddenly failing?”
- “Figure out whether this eval failure is a product regression or a harness problem.”

Bad triggers:
- “Implement a new dashboard section.”
- “Review this PR.”
- “Research the best auth library.”

---

## Troubleshooting

### Cannot reproduce
Gather the best available evidence and narrow the scope:
- specific environment
- specific user flow
- recent changes
- logs/errors

### Multiple plausible causes
Rank them and test the smallest/highest-likelihood ones first.

### Failure seems flaky
Say so explicitly. Distinguish flakiness from a confirmed regression.

### Failure spans app and environment signals
Separate what is code-backed from what is setup- or dependency-backed before proposing a fix.

---

## Trigger tests

### Should trigger

1. Investigate why the stream route is failing.
2. Triage this failing orchestrator test.
3. Reproduce the sandbox startup issue and report findings.
4. Determine whether this is a flaky browser failure.
5. Why is `npm run eval` failing on this branch?
6. Root-cause the planner misclassification.
7. Inspect these console errors and classify the issue.
8. Reproduce the frontend 502 and tell me what category of failure it is.
9. Figure out whether this quality-gate failure is product or harness.
10. Inspect and report why the evidence table is empty.

### Should not trigger

1. Implement the agreed fix for the stream route.
2. Compare implementation options for multi-turn memory.
3. Review this branch for regressions.
4. Run focused Playwright product checks for the export flow.
5. Add a new summary card to the assistant response.

## Overlap risks and metadata improvements

- Browser-flow failures overlap with `playwright-product-test`; trigger this skill when diagnosis is primary, not flow verification.
- Eval failures overlap with `golden-dataset-eval`; trigger this skill when root-cause classification matters more than running the eval workflow itself.
- Implementation requests overlap with `feature-implementation`; keeping "diagnosing" and "root cause is not yet clear" in the description helps.
