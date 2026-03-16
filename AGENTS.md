# AGENTS.md

## Project overview

This repository should be optimized for reliable agent-assisted development.
It builds a conversational analytics agent for nontechnical users that should handle complex multi-step and multi-turn questions while optimizing for low latency and high insight/data quality.

The purpose of this file is to provide:
- repo-wide policy
- routing guidance
- key commands
- definition of done

This file is intentionally thin.
Detailed task procedures belong in `.agents/skills/`.
Durable project knowledge belongs in `docs/`.

---

## Core product policy

This product operates in a governed corporate banking environment.

- Never be prescriptive. Describe what the data shows; do not recommend actions, strategies, or decisions.
- Auditability is mandatory. Numeric claims in synthesized responses must be traceable back to deterministic evidence.

- This application currently has no external installed user base; optimize for one canonical current-state implementation.
- Do not preserve or introduce compatibility bridges, migration shims, fallback codepaths, adapter layers, silent degraded behavior, or dual old/new behavior unless explicitly requested.

Prefer:
- one canonical codepath
- fail-fast diagnostics
- explicit recovery steps
- deletion of obsolete code rather than carrying it forward

Avoid:
- automatic migration logic unless explicitly requested
- compatibility glue
- silent fallback behavior
- "temporary" second codepaths that become permanent

If temporary compatibility code is truly necessary for debugging or a tightly scoped transition, it must be explicitly called out with:
  - why it exists
  - why the canonical path is insufficient
  - exact deletion criteria
  - the task / ADR / issue tracking its removal

Default stance: **delete old-state compatibility code rather than carrying it forward.**

---

## Layering rules

Use the repo with the following boundaries:

- `AGENTS.md`
  - repo-wide policy
  - routing
  - key commands
  - definition of done
- `docs/`
  - durable project knowledge
  - architecture
  - testing/evals
  - product behavior
  - cross-cutting lessons
- `.agents/skills/`
  - detailed task recipes
  - validation workflows
  - examples
  - troubleshooting

Do not bloat this file with long procedures.
Do not duplicate detailed workflows here if they belong in a skill.

---

## Universal working rules

- Plan first for medium and hard tasks.
- Prefer incremental edits over broad rewrites.
- Separate research from implementation when the implementation approach is not already fixed.
- Never claim success without validation.
- Use the most specific relevant skill instead of improvising a workflow.
- Prefer existing local patterns before inventing a new one.
- If a similar implementation likely exists elsewhere in this repo, inspect it first.
- Treat the work machine as a primary target environment.
- No code, data, or keys should be pushed from the work machine.
- Prefer cross-platform scripts (`python`, `py -3`, `python3`) and deterministic low-friction setup.
- Keep `npm ci` as the canonical install path and document setup changes in `README.md`.
- Prefer long-term enterprise stability over short-term local optimization.
- Treat `semantic_model.yaml` as the semantic-model source of truth; runtime consumers and summaries should derive from YAML rather than acting as independent authorities.
- Be explicit about uncertainty. Do not invent commands, architecture details, or workflows.
- Do not solve problems by adding fallback glue or compatibility layers unless explicitly requested.
- Keep changes easy to review and easy to revert.

---

## Resumption rule

After long chains, resumed work, context compaction, or partial progress:
- re-read the active task plan
- re-read the relevant files
- restate what is known vs assumed
- do not rely on stale assumptions

If context is weak, inspect the code and docs again before continuing.

---

## Research vs implementation

When the implementation approach is not already fixed:

1. research and choose the approach first
2. then implement in a narrower context

Do not mix broad exploration with implementation unless the task is trivially small.

Use `docs-research` for framework/library/tooling investigation and implementation recommendation.
Use `feature-implementation` once the implementation target is clear.

---

## Definition of done

A task is not done just because code was written.

A task is complete only when the relevant completion criteria are satisfied.

Use the applicable checks below:

- relevant tests pass
- lint/typecheck/build checks pass if relevant
- Playwright / browser / user-journey checks pass for user-facing changes
- golden dataset / benchmark / eval checks pass for logic, model, or answer-quality changes
- screenshots or visible verification are used when product behavior matters
- no forbidden fallback / compatibility creep was introduced
- setup/build tooling changes were validated with repo-standard setup and dev commands if relevant
- summary states:
  - what changed
  - what was validated
  - what remains uncertain
  - any follow-up risks

Do not edit tests only to make a broken implementation appear complete unless the test itself is wrong and that is explicitly justified.

---

## Skill routing

Use the most specific relevant skill instead of improvising.

- `feature-implementation`
  - scoped feature work or enhancements after the approach is chosen
- `bug-triage`
  - reproducing, isolating, and diagnosing defects or regressions before implementation
- `pr-review`
  - reviewing diffs for correctness, regressions, missing validation, and fallback creep
- `docs-research`
  - choosing or verifying implementation approaches before coding
- `playwright-product-test`
  - browser testing, E2E testing, broken user flows, Playwright regressions, product smoke checks
- `golden-dataset-eval`
  - golden datasets, benchmark runs, expected-vs-actual comparisons, regression evaluation, accuracy checks

If a task clearly matches one of these, load and follow that skill.

---

## Key commands

### Dev / run
- `npm run dev:orchestrator`
- `npm run dev:web`
- `npm run dev:sandbox-cortex`

### Build
- `npm run build`

### Lint
- `npm run lint`

### Tests
- `npm run test`

### Playwright
- No canonical npm Playwright command is defined in this repo.
- Current ad hoc local config: `npx playwright test -c .tmp-playwright/playwright.config.cjs`

### Evals / golden dataset
- `npm run eval`
- `python -m evaluation.run_experiment --name "local-eval" --description "local eval run"`

If a command is unknown, inspect the repo and docs first rather than inventing one.

---

## Project knowledge locations

Read these when relevant:
- `docs/architecture.md`
  - repo-wide system boundaries, major modules, and cross-cutting data flow
- `docs/frontend.md`
  - web app structure, stream handling, UI state, and frontend change points
- `docs/backend.md`
  - orchestrator runtime flow, stage boundaries, provider wiring, and backend change points
- `docs/api-contracts.md`
  - request/response payload shapes and boundary-level API expectations
- `docs/frontend-ux-spec.md`
  - frontend interaction direction, layout expectations, and UX constraints
- `docs/user-journeys.md`
  - critical visible product flows and high-priority regressions
- `docs/testing.md`
  - test surfaces, validation expectations, and repo-backed test commands
- `docs/evals.md`
  - eval assets, benchmark workflows, and result interpretation
- `docs/learnings.md`
  - durable cross-cutting lessons and repeated failure modes
- `docs/skills-evals.md`
  - skill-trigger examples for refining skill discovery and overlap boundaries

Detailed task workflows live in:
- `.agents/skills/*/SKILL.md`

---

## Maintenance rule

When the instruction system becomes noisy, overlapping, or contradictory:
- simplify
- consolidate
- remove stale guidance
- keep this file thin
- keep skills sharp
- keep docs durable
