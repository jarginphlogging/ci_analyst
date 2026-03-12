---
name: pr-review
description: Use for reviewing diffs, pull requests, or staged changes for correctness, regressions, missing validation, risky assumptions, and fallback or compatibility creep. Best for severity-ranked findings and evidence-based review. Trigger phrases include: review this diff, review this PR, check for regressions, audit this change, review staged changes.
---

# PR Review

## Purpose

Use this skill to review code changes with a skeptical, evidence-oriented mindset.

This skill is for review, not broad implementation.

---

## Use when

Use this skill when:
- reviewing a diff
- reviewing a PR
- reviewing staged/uncommitted changes
- checking for correctness and regression risk
- auditing whether validation is missing
- checking for fallback creep or risky assumptions

Repo-specific examples:
- reviewing orchestrator stage changes for boundary violations
- reviewing frontend diffs for streamed-state regressions
- reviewing prompt, SQL, or synthesis changes for missing eval coverage
- reviewing semantic-model consumer changes for drift away from `semantic_model.yaml`

---

## Do not use when

Do not use this skill when:
- the main need is implementing the change
- the main need is broad debugging
- the main need is researching libraries or approaches

Use `feature-implementation` for building.
Use `bug-triage` for diagnosis-first debugging.
Use `docs-research` for approach selection.

---

## Workflow

1. Inspect the diff first.
2. Understand the intent of the change.
3. Review for:
   - correctness
   - regression risk
   - missing validation
   - broken assumptions
   - edge cases
   - maintainability risk
4. Explicitly audit for:
   - compatibility bridges
   - migration shims
   - fallback codepaths
   - silent degraded behavior
   - dual old/new logic
5. Rank findings by severity.
6. Distinguish:
   - proven issue
   - likely issue
   - open question / suspicion
7. Note missing tests, Playwright checks, or evals when relevant.

Repo-specific review reminders:
- watch for planner, SQL, validation, and synthesis boundary drift
- check for contract drift across web, orchestrator, and eval surfaces
- check whether semantic meaning was patched downstream instead of changed in `semantic_model.yaml`
- call out missing product-flow validation for streamed UI or visible error-state changes

---

## Anti-fallback check

The repo prefers one canonical current-state implementation.

Flag any introduced:
- fallback glue
- silent degradation
- compatibility layers
- unnecessary dual behavior

unless explicitly justified.

---

## Validation / completion criteria

A good review should include:
- clear findings
- severity ranking
- evidence or rationale
- missing validation if relevant
- explicit note if no major issues were found

Do not manufacture findings just to produce criticism.

Repo-specific validation gaps to call out when relevant:
- missing targeted tests
- missing `npm run eval` coverage for prompt, orchestration, SQL, or synthesis changes
- missing Playwright or product-flow checks for UI-visible behavior changes
- missing build/lint coverage for broader refactors or tooling changes

---

## Examples

Good triggers:
- “Review this diff for correctness and regression risk.”
- “Check this PR for fallback creep.”
- “Audit these staged changes before I merge.”
- “Review this planner refactor for boundary violations.”
- “Review whether this frontend patch has enough validation.”

Bad triggers:
- “Implement this feature.”
- “Figure out why this bug happens.”
- “Research the best framework pattern.”

---

## Troubleshooting

### Diff is too large
Focus first on the highest-risk files and state that the diff is broad.

### Intent is unclear
Infer carefully from the changed code and nearby context; note uncertainty explicitly.

### No obvious issues found
Say so clearly instead of inventing weak findings.

### The diff mixes behavior changes and setup changes
Call out which validation is missing for each surface rather than treating the whole change as one risk bucket.

---

## Trigger tests

### Should trigger

1. Review this PR for regressions.
2. Do a code review of the changes on this branch.
3. Audit this diff for missing validation.
4. Look for fallback creep in this provider refactor.
5. Rank the issues in this patch by severity.
6. Tell me what would block merge here.
7. Review whether this change violates planner boundaries.
8. Inspect this local diff for silent degradation.
9. Review whether the tests are sufficient for this patch.
10. Audit this change set for contract drift.

### Should not trigger

1. Implement the fix for the failing stream route.
2. Investigate why the eval harness is failing on this machine.
3. Choose between two architectural approaches for semantic-model loading.
4. Run the browser flow and capture screenshots of the export issue.
5. Execute the golden dataset and summarize pass/fail.

## Overlap risks and metadata improvements

- Requests that mention bugs but point at a diff may still be review tasks; keeping "reviewing diffs, pull requests, or staged changes" prominent helps.
- Requests that ask for both review and fix may need review first and implementation second.
- Requests about browser regressions overlap with `playwright-product-test`; this skill should trigger when the primary ask is review of changes, not running the flow.
