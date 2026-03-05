# Query 1 Investigation and Fix Plan (2026-03-05)

Scope: `Show me total sales last month.`

## What We Investigated

1. Re-ran Query 1 against live `sandbox` orchestrator (`/v1/chat/stream`) and inspected full response payload + trace.
2. Verified SQL and returned row bounds from backend.
3. Traced frontend rendering path for date fields in the primary evidence table.

## Findings

### Finding A: Backend period bounds are correct
- Current backend result row:
  - `data_from = 2025-11-01`
  - `data_through = 2025-11-30`
- SQL in trace:
  - `RESP_DATE >= DATE_TRUNC('month', DATEADD('month', -1, max_dt))`
  - `RESP_DATE < DATE_TRUNC('month', max_dt)`

Conclusion: backend is returning correct prior-month bounds for this run.

### Finding B: UI date rendering causes the apparent inconsistency
- In [`apps/web/src/components/evidence-table.tsx`](/Users/joe/Code/ci_analyst/apps/web/src/components/evidence-table.tsx), date cells and x-labels use `new Date("YYYY-MM-DD")` and `toLocaleDateString()`.
- JS interprets date-only strings as UTC midnight, then shifts to local timezone.
- In ET timezone, that turns:
  - `2025-11-01` -> `10/31/2025`
  - `2025-11-30` -> `11/29/2025`

This exactly matches the mismatch recorded in the review.

### Finding C: Confidence/assumption hardening gap remains
- Even though this specific run has full month coverage, we still lack a deterministic contract check that prevents unsupported “full period” phrasing if future data is partial.
- Existing inline checks in [`apps/orchestrator/app/services/orchestrator.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/orchestrator.py) only cover answer sanity + PII.

## Plan to Fix (Constitution-Aligned)

Principles applied:
- No hardcoding to Query 1.
- Keep LLM for semantics, add Python/UI contract checks for safety and consistency.
- Generalizable for all date-only fields and period statements.

### Phase 1 (P0): Fix date-only rendering in web UI

Files:
- [`apps/web/src/components/evidence-table.tsx`](/Users/joe/Code/ci_analyst/apps/web/src/components/evidence-table.tsx)

Changes:
1. Add a date-only parser helper for `YYYY-MM-DD` that constructs local calendar dates (no UTC shift).
2. Update `formatCell(..., "date")` to use the safe parser first.
3. Update `formatXLabel` to use the same safe parser path for date-only values.
4. Keep existing parsing path for full timestamps (`YYYY-MM-DDTHH:mm:ssZ`) to preserve expected behavior.

Expected outcome:
- Evidence table and chart labels show exact stored date values (no -1 day drift).

### Phase 2 (P0): Add regression tests for date-only rendering

Files:
- [`apps/web/src/components/evidence-table.test.tsx`](/Users/joe/Code/ci_analyst/apps/web/src/components/evidence-table.test.tsx)

Changes:
1. Add test that renders date cells for `2025-11-01` / `2025-11-30` and asserts displayed dates remain Nov 1 / Nov 30 (not Oct 31 / Nov 29).
2. Add test for `formatXLabel` behavior via chart-rendered labels with date-only x values.
3. Ensure tests are timezone-robust by asserting calendar intent (month/day strings) from rendered output, not raw `Date` internals.

Expected outcome:
- CI catches any future reintroduction of timezone drift.

### Phase 3 (P1): Add period-coverage confidence guardrail in orchestrator

Files:
- [`apps/orchestrator/app/evaluation/inline_checks_v2_1.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/evaluation/inline_checks_v2_1.py)
- [`apps/orchestrator/app/services/orchestrator.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/orchestrator.py)

Changes:
1. Add an inline check that flags unsupported full-coverage claims in answer/assumptions when coverage cannot be established.
2. If flagged:
  - downgrade `confidence` from `high` -> `medium`,
  - append a neutral assumption about potential partial-period effects.
3. Keep logic generic (keyword-driven + evidence-presence-driven), not tied to “last month” only.

Expected outcome:
- When period completeness is uncertain, user-facing confidence and assumptions remain conservative and accurate.

### Phase 4 (P1): Strengthen synthesis prompt contract for completeness language

Files:
- [`apps/orchestrator/app/prompts/markdown/synthesis_system.md`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/markdown/synthesis_system.md)

Changes:
1. Explicit instruction: do not claim “full month/quarter” unless context explicitly supports it.
2. If coverage is unknown/limited, require caveated language.

Expected outcome:
- Better first-pass LLM behavior; fewer post-check corrections.

## Validation Checklist

1. Backend reproduction:
   - Query 1 returns `data_from`/`data_through` unchanged in API payload.
2. Frontend visual validation:
   - Primary table shows Nov 1 and Nov 30 exactly.
3. Automated tests:
   - `npm --workspace @ci/web run test` includes new date rendering regressions.
4. Confidence safety:
   - Synthetic partial-period fixture downgrades confidence and adds caveat via inline checks.

## Risks and Mitigations

- Risk: date parsing changes may affect timestamp rendering.
  - Mitigation: branch logic for date-only vs timestamp strings and add both test types.
- Risk: conservative confidence downgrades too often.
  - Mitigation: guardrail only triggers when full-coverage claim text is present without supporting evidence.

## Deliverable Definition of Done

- Query 1 no longer shows off-by-one dates in UI.
- Query 1 narrative/table period consistency is preserved end-to-end.
- Regression tests cover date-only rendering path.
- Confidence/assumption handling is robust when period completeness is ambiguous.
