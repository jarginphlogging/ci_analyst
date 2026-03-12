---
name: docs-research
description: Use for researching or verifying framework, library, tooling, or implementation approaches before coding. Best for separating decision-making from implementation, inspecting local patterns first, and producing a concise recommended approach. Trigger phrases include: research this approach, verify best practice, how should we implement this, check the docs, compare options before coding.
---

# Docs Research

## Purpose

Use this skill to choose or verify an implementation approach before writing code.

This skill helps keep implementation context clean by separating research from building.

---

## Use when

Use this skill when:
- the implementation approach is not yet fixed
- a library/framework/tooling pattern needs verification
- multiple implementation options are possible
- local repo usage should be inspected before making changes

Repo-specific examples:
- deciding whether a change belongs in contracts, prompts, stage logic, or `semantic_model.yaml`
- verifying the right pattern for streamed UI behavior in `apps/web`
- comparing where orchestration logic should live across planner, SQL, validation, and synthesis boundaries
- checking whether a prompt, eval, or provider integration pattern already exists locally

---

## Do not use when

Do not use this skill when:
- the approach is already chosen and implementation should begin
- the task is primarily debugging
- the task is primarily review-only

Use `feature-implementation` once the implementation target is clear.
Use `bug-triage` when diagnosis is the main job.
Use `pr-review` when reviewing an existing diff.

---

## Workflow

1. Restate the decision that needs to be made.
2. Inspect local repo usage and patterns first.
3. Consult relevant docs or references if needed.
4. Compare options only as much as necessary.
5. Produce a concise recommendation:
   - chosen approach
   - why
   - constraints
   - affected files or layers
   - validation expectations
6. Hand off to implementation with a clear target.

Repo-specific research reminders:
- prefer existing repo patterns before importing a new one
- keep semantic meaning in `semantic_model.yaml` rather than patching downstream logic
- keep stage responsibilities separate when evaluating orchestration changes
- use authoritative docs when the question is about framework, library, or provider behavior

---

## Output expectations

A good output should be concise and implementation-ready.

Include:
- recommended approach
- why it is preferred here
- important tradeoffs
- version/usage caveats if relevant
- next implementation step

Do not produce an unnecessarily broad research memo.

---

## Examples

Good triggers:
- “Research the best way to implement this in our current stack.”
- “Check the docs and verify the recommended pattern before coding.”
- “Compare these two implementation options and recommend one.”
- “Figure out whether this belongs in prompts, contracts, or the semantic model.”
- “Verify the provider docs and recommend how to wire this in.”

Bad triggers:
- “Build this feature now.”
- “Review this diff.”
- “Debug this failing test.”

---

## Troubleshooting

### Too many possible options
Narrow based on this repo’s current stack and local patterns.

### Docs conflict with local usage
Prefer a recommendation that fits the repo unless local usage is clearly wrong and should be changed.

### External docs are unstable or ambiguous
State the uncertainty, cite the authoritative source used, and recommend the lowest-risk implementation path.

---

## Trigger tests

### Should trigger

1. Research the right approach for multi-turn memory before we implement it.
2. Verify the provider docs and recommend how to wire structured output.
3. Which pattern should we use for streaming status events in this repo?
4. Compare options for keeping semantic-model logic out of prompt text.
5. Decide how the eval harness should consume this new field.
6. Research whether this change belongs in contracts, prompts, or the semantic model.
7. Verify the retry behavior docs and recommend an implementation plan.
8. Figure out the cleanest approach for a new product-flow test.
9. Research how to organize a new repo-local skill without bloating AGENTS.
10. Recommend whether this should use Playwright or a smaller deterministic check.

### Should not trigger

1. Implement the approved provider retry change.
2. Triage why sandbox startup is failing today.
3. Review this PR for correctness and missing tests.
4. Run the current Playwright flow and capture console errors.
5. Execute the golden dataset and summarize the regressions.

## Overlap risks and metadata improvements

- Broad “help me with X” prompts overlap with `feature-implementation`; keeping "before coding" and "approach is not yet fixed" explicit helps.
- Some investigative requests overlap with `bug-triage`; this skill is for design uncertainty, not failure diagnosis.
- Requests to compare libraries or provider behaviors can sprawl; keeping "produce a concise recommended approach" in the description helps contain scope.
