# Learnings

Use this file for durable cross-cutting lessons, recurring gotchas, and repeated Codex failure modes.

## Purpose

This document stores durable cross-cutting lessons for this repository.

Use it for:
- recurring gotchas
- repeated Codex failure modes
- non-obvious constraints
- durable "do X, not Y" lessons

Do not use this as:
- a scratchpad
- a task log
- a dump of temporary debugging notes
- a duplicate of architecture or skills content

Keep entries concise and high-signal.

---

## Learnings

### Prefer canonical implementations over fallback glue
Codex tends to introduce fallback paths, compatibility shims, and dual old/new behavior. In this repo, prefer one canonical codepath, fail-fast diagnostics, and explicit recovery steps unless compatibility behavior is explicitly requested.

### Thin top layer, rich lower layers
Keep `AGENTS.md` thin. Put durable project knowledge in `docs/`. Put detailed workflows in skills. Do not turn `AGENTS.md` into a procedural dump.

### Separate research from implementation
When the implementation approach is unclear, research first and implement second. Mixing exploration and implementation creates noisy context and weaker changes.

### Re-ground after long chains
After long sessions, resumed work, or compacted context, re-read the active plan and relevant files. Do not trust stale assumptions.

### Use the most specific skill
If a task clearly matches a skill, use that skill instead of improvising. Broad improvisation creates inconsistent workflows and weaker validation.

### Validation is part of the task
Do not treat testing, Playwright checks, or evals as optional post-work. They are part of completion.

### Prefer targeted validation over broad expensive validation
Start with the smallest relevant tests, evals, or product flows first. Escalate only when the risk or evidence justifies it.

### Neutral investigation beats biased investigation
For debugging and review, prefer inspect-and-report findings over prompts that assume a bug or demand a specific outcome. Biased framing produces weaker findings.

### Reuse local patterns before inventing new ones
Before creating a new pattern, inspect the repo for an existing one. Consistency is usually better than novelty.

### Keep business meaning in the semantic model
Business meaning should live in `semantic_model.yaml`, not in one-off prompt logic, Python glue, or UI heuristics. Derived runtime views are consumers, not separate truth.

### Keep stage boundaries hard
Planner, SQL, validation, and synthesis should not blur together. Stage drift creates subtle correctness, audit, and trust regressions.

### Durable docs beat giant memory blobs
Stable knowledge should live in focused docs. Avoid sprawling generic memory files that become junk drawers.

---

## Update rule

Add a new learning only if it is:
- durable
- cross-cutting
- likely to matter again

If it is temporary, task-specific, or procedural, it belongs somewhere else.
