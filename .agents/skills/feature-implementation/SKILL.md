---
name: feature-implementation
description: Use for scoped feature work, enhancements, or implementation tasks after the approach is already chosen. Best for implementing a clear plan, making incremental code changes, validating the result, and checking for fallback or compatibility creep. Trigger phrases include: implement this feature, add this behavior, build this change, make this enhancement, wire this up, code this plan.
---

# Feature Implementation

## Purpose

Use this skill for implementation work when the desired approach is already chosen or sufficiently clear.

This skill is for building.
It is not the default skill for broad research or generic debugging.

---

## Use when

Use this skill when:
- implementing a scoped feature
- adding a defined enhancement
- wiring up already-decided behavior
- executing a concrete plan
- making code changes where success criteria are relatively clear

Repo-specific examples:
- wiring a chosen field through contracts, orchestrator, and UI
- implementing a selected planner, SQL, validation, or synthesis change
- making a targeted UI behavior change in `apps/web`
- changing semantic-model consumers after the semantic change is already decided in `semantic_model.yaml`

---

## Do not use when

Do not use this skill when:
- the implementation approach is still unclear
- the main need is framework/library research
- the main need is reproducing an unknown bug
- the task is primarily review-only

Use `docs-research` first if the approach is not yet settled.
Use `bug-triage` if the main problem is diagnosis.
Use `pr-review` if the main job is reviewing a diff.

---

## Workflow

1. Inspect the relevant files and surrounding local patterns.
2. Restate the implementation target clearly.
3. Make a short implementation plan.
4. Prefer the smallest safe change that satisfies the requirement.
5. Implement incrementally.
6. Reuse local patterns before introducing new ones.
7. Keep semantic meaning in `semantic_model.yaml`, not in one-off prompt logic, Python glue, or UI heuristics.
8. Keep planner, SQL, validation, and synthesis responsibilities in their intended boundaries.
9. Run the most relevant validation.
10. Check explicitly for:
   - fallback glue
   - compatibility shims
   - silent degraded behavior
   - dual old/new codepaths
11. Summarize:
   - what changed
   - what was validated
   - what remains uncertain

---

## Anti-fallback check

Do not solve feature work by adding compatibility bridges, migration shims, or fallback codepaths unless explicitly requested.

Prefer:
- one canonical implementation
- fail-fast diagnostics
- explicit recovery steps

If temporary compatibility behavior is truly necessary, call it out explicitly with why it exists and how it will be removed.

---

## Validation / completion criteria

A feature task is not complete unless the relevant checks are done.

Use the applicable checks:
- targeted tests
- lint/typecheck/build if relevant
- Playwright/product-flow validation if user-facing behavior changed
- eval/golden dataset checks if answer quality or logic changed

Repo-specific validation expectations:
- use `npm run test`, workspace-level tests, `npm run lint`, and `npm run build` when relevant
- use focused Playwright checks for streamed UI, visible state, and error/recovery changes
- use `npm run eval` first for prompt, orchestration, SQL, synthesis, or answer-quality changes
- if semantic meaning changed, validate the YAML-driven behavior through the affected planner, SQL, and eval surfaces

State clearly what was validated and what was not.

---

## Examples

Good triggers:
- “Implement the approved approach for the new filter UI.”
- “Add support for this analytics summary card using the existing pattern.”
- “Wire this backend field through to the UI.”
- “Implement the plan from the docs-research pass.”
- “Remove the old path and keep the selected canonical implementation.”

Bad triggers:
- “Figure out what auth approach we should use.”
- “Search the codebase and find bugs.”
- “Review this diff.”

---

## Troubleshooting

### The task is broader than expected
Split into:
- research/decision
- implementation

### Local patterns conflict
Prefer the most current and clearly intentional local pattern. Note uncertainty if necessary.

### Validation is unclear
Inspect `docs/testing.md`, `docs/evals.md`, and the local test/eval setup before guessing.

### The change starts drifting across stage boundaries
Stop and re-check whether the logic belongs in planner, SQL, validation, synthesis, contracts, or the semantic model before adding more code.

---

## Trigger tests

### Should trigger

1. Implement the selected planner change.
2. Add the approved summary card to the frontend.
3. Wire the chosen provider path into the orchestrator.
4. Refactor this code to keep only the new canonical path.
5. Finish the agreed export behavior.
6. Implement the selected validation error contract.
7. Remove the outdated flow and keep the approved one.
8. Build the chosen trace metadata field end to end.
9. Apply the approved prompt-schema change.
10. Make this agreed refactor work and run validation.

### Should not trigger

1. Which implementation approach should we use here?
2. Investigate why this is failing in CI.
3. Review this branch for regressions.
4. Run the browser flow and capture console errors.
5. Execute the golden dataset and summarize failures.

## Overlap risks and metadata improvements

- Requests that sound like bug fixes overlap with `bug-triage` when root cause is unknown; this skill should fire only when the implementation direction is already chosen.
- Design-choice requests overlap with `docs-research`; keeping "after the approach is already chosen" in the description helps.
- Review-only requests overlap with `pr-review`; "implementation tasks" and "code changes" should remain explicit in discovery metadata.
