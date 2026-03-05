# Query 4 Fix Plan (2026-03-05)

## Scope
Starter query 4:

> What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?

## Issues Encountered
1. Historical correctness defect (from 2026-03-04 review): derived comparison columns mixed metric families (avg sale vs sales baseline), producing nonsensical deltas.
2. Intermittent runtime failure during validation runs: `run_sql() got an unexpected keyword argument 'temporal_scope'` when stale dev processes were active.
3. Remaining quality/latency defect after correctness fix: planner intermittently decomposed this into 2 independent period tasks instead of 1 comparison task, increasing latency and token spend.

## Minimum Effective Solution (Constitution-aligned)
- Keep semantics in the LLM, avoid hardcoded Python routing logic.
- Apply a prompt-level planner contract update:
  - Split only for truly incompatible windows (different grains/filters/entities).
  - Prefer one task when the same metric set is requested at the same grain across two periods.
- Add a regression test that asserts this planner policy text remains in the system prompt.

Implemented changes:
- `apps/orchestrator/app/prompts/markdown/planner_system.md`
- `apps/orchestrator/tests/test_planner_stage.py`

## Validation
- Unit tests:
  - `npm --workspace @ci/orchestrator run test -- tests/test_planner_stage.py`
  - Result: 10 passed.
- Playwright replay (UI):
  - Query 4 completed successfully.
  - `Preparing data retrieval for step 1/1` shown in UI.
  - Orchestrator logs confirm `stepCount: 1`, `queryCount: 1`.
  - Output table shows coherent YoY deltas for all three metrics.

## Remaining Operational Guardrail
For deterministic local validation, run a single orchestrator process and avoid stale/redundant reload workers before Playwright replay.
