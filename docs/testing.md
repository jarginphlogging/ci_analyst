# Testing

Use this file for durable testing guidance, validation expectations, and repo-backed test commands.

## Purpose

This document explains how testing works in this repository.

It should help answer:
- what kinds of tests exist
- how to run them
- when to use which test strategy
- what validation is expected before declaring a task complete

This is durable testing guidance, not a one-off debug log.

---

## Testing philosophy

Tests are one of the main task completion gates in this repo.

Do not treat a task as complete simply because code was written.

Prefer:
- targeted validation first
- deterministic checks where possible
- validation that matches the change
- explicit reporting of what was validated

Do not:
- edit tests only to force a passing outcome unless the test itself is incorrect and that is explicitly justified
- declare success without evidence
- skip relevant validation because a change seems "small"

Additional repo-specific guidance:
- prompts are code, so prompt changes should be validated like code changes
- prefer deterministic checks before AI-judged ones whenever the quality being tested can be verified mechanically
- regression protection outranks isolated one-off wins
- planner / SQL / synthesis boundary tests are especially valuable in this repo
- semantic-model meaning changes should start in `semantic_model.yaml`, then be validated through the affected planner, SQL, and eval surfaces
- stage-boundary violations are high-priority regressions because they create subtle correctness and trust failures
- work-machine setup should stay deterministic, low-friction, and cross-platform where practical

---

## Test categories

### Unit and integration tests

- Purpose:
  - validate orchestrator stages, provider wiring, SQL guardrails, contracts, and core frontend rendering/stream parsing
- When to run it:
  - backend changes
  - frontend logic changes
  - contract changes
  - most refactors
- Command(s):
  - `npm run test`
  - `npm --workspace @ci/orchestrator run test`
  - `npm --workspace @ci/web run test`
  - `npm --workspace @ci/eval-harness run test`
- Typical speed / scope:
  - targeted workspace tests are the fastest useful default
  - root `npm run test` runs all workspace test scripts
- Common failure patterns:
  - contract drift between frontend and backend
  - orchestrator stage regressions
  - stream parsing regressions
  - stale assertions after intentional behavior changes

### End-to-end / Playwright tests

- Purpose:
  - validate user-visible browser flows, visible state transitions, console errors, and important network failures
- When to run it:
  - user-facing UI changes
  - streamed UX changes
  - error/loading/completion-state changes
- Command(s):
  - no canonical npm Playwright command is currently defined
  - current ad hoc local config exists at `.tmp-playwright/playwright.config.cjs`
  - current ad hoc local command: `npx playwright test -c .tmp-playwright/playwright.config.cjs`
- Typical speed / scope:
  - slower and broader than unit/integration checks
  - should usually be focused to one product flow rather than used as a broad default
- Common failure patterns:
  - environment setup problems
  - stale ad hoc test scripts
  - UI state regressions not caught by unit tests

### Benchmark / golden dataset / eval tests

- Purpose:
  - compare actual versus expected answer behavior, numeric assertions, latency, and prompt-driven behavioral changes
- When to run it:
  - orchestration changes
  - prompt changes
  - answer-quality changes
  - logic changes that affect outputs
- Command(s):
  - `npm run eval`
  - `python -m evaluation.run_experiment --name "local-eval" --description "local eval run"`
  - see `docs/evals.md` for broader eval stack commands
- Typical speed / scope:
  - `npm run eval` is the fast local path
  - Python evaluation workflows are broader and heavier
- Common failure patterns:
  - expected-vs-actual mismatch
  - harness or dataset issues misread as product regressions
  - environment/service availability issues

### Lint / build validation

- Purpose:
  - catch syntax, packaging, and build-surface regressions
- When to run it:
  - code changes that affect buildable or linted surfaces
  - setup/tooling changes
- Command(s):
  - `npm run lint`
  - `npm run build`
- Typical speed / scope:
  - root commands run workspace scripts where present
- Common failure patterns:
  - one workspace lacking a script while another one fails
  - build-only regressions that do not appear in tests

### Typecheck validation

- Purpose:
  - catch static typing regressions where the repo exposes a stable typecheck command
- When to run it:
  - TypeScript-heavy changes, if a canonical typecheck command exists
- Command(s):
  - no canonical root or workspace `typecheck` script is currently defined
- Typical speed / scope:
  - currently not a stable repo-wide validation surface
- Common failure patterns:
  - assuming build or lint is a formal standalone typecheck step

---

## Key commands

### Unit / integration tests
- `npm run test`
- `npm --workspace @ci/orchestrator run test`
- `npm --workspace @ci/web run test`
- `npm --workspace @ci/eval-harness run test`

### Lint
- `npm run lint`

### Typecheck
- no canonical repo `typecheck` command is currently defined

### Build
- `npm run build`

### Playwright
- no canonical npm Playwright command is currently defined
- current ad hoc local command: `npx playwright test -c .tmp-playwright/playwright.config.cjs`

### Eval / benchmark
- `npm run eval`
- `python -m evaluation.run_experiment --name "local-eval" --description "local eval run"`

If a command is unknown, inspect package/config files rather than guessing.

---

## Validation expectations by change type

### Small internal refactor
- run the most relevant targeted tests
- run lint/build if relevant
- preserve behavior

### Backend / logic change
- run targeted tests for the changed area
- run broader integration checks if risk is moderate/high
- run evals if answer quality or logic behavior may change
- if the change affects semantic meaning, validate the YAML-driven behavior rather than patching downstream logic alone

### UI / product behavior change
- run targeted product validation
- use Playwright when appropriate
- verify visible behavior, not just compilation

### Answer quality / model / orchestration change
- run golden dataset / benchmark subset first
- compare actual vs expected
- summarize deltas

### Setup / tooling change
- validate:
  - `npm ci`
  - `npm run setup:orchestrator`
  - `npm run dev:orchestrator`
  - `npm run dev:web`
- prefer enterprise-stable changes over local-only optimizations

---

## Failure handling

When tests fail:
- distinguish implementation failures from test failures
- distinguish environment/setup issues from real regressions
- do not patch with fallback glue
- isolate the smallest meaningful failing scope first

If the failure is unclear, document:
- what failed
- what was expected
- likely causes
- what still needs confirmation

Repo-specific failure classes:
- app failure
- test failure
- environment failure
- flaky failure

---

## Completion rule

Relevant tests and validation should be treated as part of the task, not as optional post-work.

A good final summary should state:
- which tests were run
- which checks passed
- which checks were not run and why
- what residual risk remains
