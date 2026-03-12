---
name: playwright-product-test
description: Use for Playwright-based end-to-end product testing, browser regressions, broken user flows, UI smoke tests, visible behavior checks, console errors, and important network failures. Best for targeted product-flow validation rather than generic full-suite runs. Trigger phrases include: run Playwright, test this flow, browser regression, end-to-end test, product smoke test, broken user flow, validate UI behavior.
---

# Playwright Product Test

## Purpose

Use this skill for user-facing browser and product-flow validation.

This is not a generic testing skill.
It is specifically for validating visible behavior and important user journeys.

---

## Use when

Use this skill when:
- UI/product behavior changed
- a user flow may have broken
- a browser regression is suspected
- a targeted product smoke check is needed
- Playwright is the appropriate validation tool

Repo-specific examples:
- validating the streamed chat flow after UI changes
- checking startup, follow-up, error, or evidence-table flows in the web app
- confirming visible behavior after changes to `apps/web/src/components/agent-workspace.tsx`
- checking console errors or failed network requests around `/api/chat/stream`

---

## Do not use when

Do not use this skill when:
- only backend/unit logic changed and browser validation is not relevant
- the main need is benchmark/golden dataset evaluation
- the main need is generic implementation or review

Use `bug-triage` when diagnosis is primary.
Use `golden-dataset-eval` for eval and benchmark workflows.
Use `feature-implementation` or `pr-review` for build or review work.

---

## Workflow

1. Locate the Playwright setup and relevant test entry points.
2. Identify the most relevant user-facing flows for the change.
3. Prefer targeted runs over broad expensive suites.
4. Validate:
   - navigation
   - user actions
   - visible state
   - loading/error behavior
   - console errors
   - important network failures
5. Capture useful artifacts if available:
   - screenshots
   - traces
   - videos
   - logs
6. Distinguish:
   - app failure
   - test failure
   - environment/setup issue
   - flaky behavior
7. Stop once enough evidence exists to report clearly.
8. Summarize findings in a debugging-friendly way.

Repo-specific execution notes:
- there is no canonical repo-wide Playwright npm script today
- current local Playwright usage is centered on `.tmp-playwright/playwright.config.cjs` and narrow runner scripts/artifacts
- prefer one focused query or flow over broad multi-flow sweeps unless the change is broad
- use `docs/user-journeys.md` to choose the highest-value flows first

---

## Validation / completion criteria

A good Playwright/product check should state:
- which flow(s) were tested
- which targeted runs were used
- pass/fail status
- visible failures
- console/network issues
- captured artifacts
- whether the failure looks like:
  - app
  - test
  - environment
  - flaky

Repo-specific validation examples:
- startup/workspace rendering
- main streamed query flow
- results rendering with evidence, confidence, assumptions, and trace
- follow-up question behavior
- explicit error/recovery behavior
- evidence fallback-table rendering

---

## Examples

Good triggers:
- “Run targeted Playwright on the changed flows.”
- “Validate this browser regression.”
- “Test the main query flow after this UI change.”
- “Check whether this user journey is broken.”
- “Verify the loading-to-response transition in the chat UI.”

Bad triggers:
- “Run every test in the repo.”
- “Evaluate answer quality on the benchmark set.”
- “Implement this feature.”

---

## Troubleshooting

### Test suite is large
Run only the smallest relevant subset first.

### Failure source is unclear
Classify explicitly:
- app behavior problem
- Playwright/test issue
- environment issue
- flake

### No clear flow documentation exists
Consult `docs/user-journeys.md` and inspect existing Playwright tests or `.tmp-playwright` scripts to infer the highest-value journeys.

### The setup looks ad hoc
State that clearly. Use the current local Playwright entry points and artifacts, but do not pretend they are a stabilized permanent suite contract.

---

## Trigger tests

### Should trigger

1. Use Playwright to test the streamed chat flow.
2. Check whether the export button works in the data explorer.
3. Run a focused browser test for the error-state UI.
4. Validate the main product flow and capture screenshots.
5. Inspect console errors during the suggested-question flow.
6. Check for important failed network requests in the chat stream.
7. Re-run this flaky browser scenario.
8. Test whether the trace panel still renders.
9. Exercise the starter prompts and report broken visible states.
10. Verify the loading-to-response transition in the UI.

### Should not trigger

1. Review this PR for regressions and missing validation.
2. Investigate why the backend sandbox service fails to boot.
3. Run the golden dataset and summarize failures.
4. Research which browser-testing approach we should use before adding tests.
5. Implement the agreed fix for the data explorer export button.

## Overlap risks and metadata improvements

- Browser failures overlap with `bug-triage`; trigger this skill when flow validation is primary.
- Requests about adding or redesigning browser tests overlap with `docs-research`; keep "targeted product-flow validation" prominent.
- Requests about broad repo test runs overlap with general testing work; keep "visible behavior, console errors, and important network failures" explicit.
