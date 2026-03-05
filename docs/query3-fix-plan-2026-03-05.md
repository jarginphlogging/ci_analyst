# Query 3 Investigation and Fix Plan (2026-03-05)

Scope: `Show me new vs repeat customers by month for the last 6 months.`

## What We Investigated

1. Reviewed findings in [`docs/playwright-starter-query-review-2026-03-04.md`](/Users/joe/Code/ci_analyst/docs/playwright-starter-query-review-2026-03-04.md).
2. Traced SQL generation and execution contracts in orchestrator prompts + inline checks.
3. Traced chart/date rendering path in web (`EvidenceTable`).
4. Reproduced likely SQL off-by-one behavior directly against sandbox SQLite seed data.

## Findings

### Finding A: Temporal contract is not enforced in the SQL path
- SQL generation prompt currently has no deterministic requirement for “last N months/weeks” bounds (see [`apps/orchestrator/app/prompts/markdown/sql_user.md`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/markdown/sql_user.md)).
- Inline checks validate syntax/row-count/PII only; no time-window correctness check (see [`apps/orchestrator/app/evaluation/inline_checks_v2_1.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/evaluation/inline_checks_v2_1.py)).

### Finding B: `last 6 months` can easily become 7 months with common SQL pattern
- Reproduced in sandbox DB:
  - `resp_date >= DATEADD('MONTH', -6, max_date) AND resp_date <= max_date`
  - grouped by month returns **7** months (`2025-06-01` through `2025-12-01`).
- Correct 6-month calendar window ending at max available month is:
  - start at `DATE_TRUNC('MONTH', DATEADD('MONTH', -5, max_date))`
  - end at `LAST_DAY(max_date)`
  - grouped by month returns **6** months (`2025-07-01` through `2025-12-01`).

### Finding C: `May 2025` x-axis tick is a frontend timezone rendering bug
- In [`apps/web/src/components/evidence-table.tsx`](/Users/joe/Code/ci_analyst/apps/web/src/components/evidence-table.tsx), `formatXLabel` uses `new Date("YYYY-MM-DD")` + `toLocaleDateString`.
- In US timezones, date-only strings are interpreted as UTC midnight, then displayed in local time, which can shift `2025-06-01` to May.
- This explains the unexpected `May 2025` label even when data is June+.

## Plan to Fix (Constitution-Aligned)

Principles applied:
- No hardcoding to Query 3.
- Preserve LLM semantic flexibility.
- Add Python/UI contracts to enforce correctness and consistency.

### Phase 1 (P0): Introduce a reusable temporal-intent contract in orchestrator

Files:
- new `apps/orchestrator/app/services/temporal_contract.py`
- wire into [`apps/orchestrator/app/services/stages/sql_stage.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/stages/sql_stage.py)

Changes:
1. Parse explicit relative windows from user text in a general form (`last N day/week/month/quarter/year`, plus singular forms like `last month`).
2. Resolve expected bounds against dataset max date for calendar units.
3. Expose normalized contract per turn/step (`unit`, `count`, `start_date`, `end_date`, `expected_periods`).

Why this fits constitution:
- LLM still decides semantic mapping and SQL design.
- Python only enforces explicit user-requested period contracts as safety.

### Phase 2 (P0): Enforce temporal contract after SQL execution with bounded retry feedback

Files:
- [`apps/orchestrator/app/services/stages/sql_stage.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/stages/sql_stage.py)
- [`apps/orchestrator/app/services/stages/sql_state_machine.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/stages/sql_state_machine.py)

Changes:
1. After each step execution, inspect date-like columns in returned rows.
2. Validate:
  - min/max date coverage within expected bounds,
  - expected distinct period count for explicit `last N months/weeks` requests.
3. If violated:
  - raise a structured execution failure code (temporal window mismatch),
  - feed bounded retry feedback into regeneration loop,
  - avoid silent wrong answers.

### Phase 3 (P0): Strengthen SQL generation prompt with explicit temporal guardrails

Files:
- [`apps/orchestrator/app/prompts/markdown/sql_system.md`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/markdown/sql_system.md)
- [`apps/orchestrator/app/prompts/markdown/sql_user.md`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/markdown/sql_user.md)
- [`apps/orchestrator/app/prompts/templates.py`](/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/templates.py)

Changes:
1. Pass normalized temporal contract into SQL prompt when available.
2. Add explicit rules for calendar windows:
  - use resolved start/end dates,
  - do not expand beyond requested `N` periods,
  - include bounded rationale in assumptions when truncation/partial-period behavior is applied.

### Phase 4 (P0): Fix date-only chart/date rendering in frontend

Files:
- [`apps/web/src/components/evidence-table.tsx`](/Users/joe/Code/ci_analyst/apps/web/src/components/evidence-table.tsx)

Changes:
1. Add a date-only parser for `YYYY-MM-DD` that constructs local calendar dates (`new Date(year, month-1, day)`), avoiding UTC shift.
2. Use that parser in both `formatXLabel` and date cell formatting.
3. Preserve existing behavior for full timestamps.

### Phase 5 (P0): Add regression tests for both backend and frontend defects

Files:
- new `apps/orchestrator/tests/test_temporal_contract.py`
- update `apps/orchestrator/tests/test_sql_stage_parallel.py`
- update `apps/web/src/components/evidence-table.test.tsx`

Changes:
1. Backend tests:
  - `last 6 months` contract resolves to exactly six month buckets (Jul-Dec for max date Dec 2025 seed).
  - SQL execution retry path triggers on temporal mismatch.
2. Frontend tests:
  - date-only monthly labels render correct month names in timezone-agnostic assertions (no May-shift for June 1).

## Validation Checklist

1. Orchestrator unit tests:
  - temporal contract parser and enforcement pass.
2. Web tests:
  - `EvidenceTable` date-only rendering regressions pass.
3. Manual replay of starter Query 3:
  - result contains exactly 6 months,
  - chart axis starts at requested window month,
  - narrative, table, and chart period range match.
4. Starter-suite acceptance:
  - period-bound checks pass for Query 1, 3, and 5 (`last month`, `last 6 months`, `last 8 weeks`).

## Risks and Mitigations

- Risk: over-filtering when date columns are absent.
  - Mitigation: enforce only when date evidence is detectable; otherwise keep soft warning + prompt constraint.
- Risk: interpretation ambiguity of relative windows across prompts.
  - Mitigation: deterministic contract only for explicit relative forms; leave ambiguous phrasing to LLM with conservative assumptions.

## Definition of Done

- Query 3 returns exactly requested 6-month window end-to-end.
- No timezone-induced month drift in chart labels.
- Temporal window correctness is enforced as a reusable contract, not query-specific logic.
