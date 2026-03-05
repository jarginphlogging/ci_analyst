# Playwright Review: Initial 6 Starter Queries

Date: 2026-03-04 (America/New_York)  
Environment: `apps/web` on `http://localhost:3000`, backend in `sandbox` mode (`orchestrator` + `sandbox-cortex`)

## Summary
- Ran all six initial starter queries one at a time through the UI.
- 5/6 returned answers; 1/6 failed with clarification + no result payload.
- Major quality issues are correctness/consistency defects, not formatting.

## Query-by-Query Findings

### 1) `Show me total sales last month.`
Judgment: **Mostly good, minor trust issue**

What worked:
- Correctly returned a single KPI-style answer with supporting table.
- Good directness and concise narrative.

What to improve:
- Date inconsistency: narrative says full month (`Nov 1–30, 2025`) but raw data table ends at `11/29/2025`.
- If data is partial, response should explicitly say partial-month coverage and adjust confidence.

### 2) `Show me sales by state in descending order.`
Judgment: **Needs correction**

What worked:
- Returned ranked state table in descending order with full list.
- Presentation intent (`ranked table`) matches request.

What to improve:
- Narrative contradiction: says California is second, but table shows California rank 30.
- This is a high-severity synthesis QA miss (narrative must be validated against returned rows before rendering).

### 3) `Show me new vs repeat customers by month for the last 6 months.`
Judgment: **Partially correct, period handling bug**

What worked:
- Good comparison framing between new vs repeat.
- Useful line chart and derived insights.

What to improve:
- Returned 7 months (`Jun–Dec 2025`) for a 6-month request.
- Chart tick labels include `May 2025`, which further conflicts with request scope.
- Need strict temporal window enforcement from planner -> SQL -> synthesis.

### 4) `What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?`
Judgment: **High-value answer with critical computed-column bug**

What worked:
- Topline YoY narrative is clear and mostly sensible.
- KPIs map directly to user intent.

What to improve:
- Comparison table has broken derived columns:
  - `Δ Avg Sale 2025 vs Sales 2024`
  - `%Δ Avg Sale 2025 vs Sales 2024`
  - Values are nonsensical (e.g., `-$259,073,200.70`, `-100.0%`).
- Column naming indicates metric mismatch (avg sale delta compared against total sales baseline).
- Add metric lineage checks before final response serialization.

### 5) `For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?`
Judgment: **Useful output, intent alignment is incomplete**

What worked:
- Correctly identified separate winners for avg ticket and transaction volume.
- Good quantitative framing and large evidence table.

What to improve:
- Ranking table is sorted by avg ticket, not by transaction volume, despite dual-objective question.
- Should return either:
  - two ranked sections/tables (one per objective), or
  - one table with dual ranks (`rank_by_avg_ticket`, `rank_by_volume`).
- Right-rail period metadata displayed `As of Mar 4, 2026` instead of explicit 8-week range.

### 6) `What were my top and bottom performing stores for 2025, what was the new vs repeat customer mix for each one, and how does that compare to the prior period?`
Judgment: **Failed**

Observed behavior:
- Pipeline stopped with clarification: asked user to provide store IDs / top-N size.
- UI shows `Request Failed` and no result payload.

Root issue (from trace):
- Planner produced dependent steps correctly.
- Step 1 generated SQL for top/bottom stores.
- Step 2 then requested clarification because prior-step entities were not propagated into the next step context.

Why this matters:
- This is a core multi-step orchestration regression. The system cannot complete a canonical decomposition pattern (`find entities -> analyze same entities`) without unnecessary user intervention.

## Cross-Cutting Improvement Priorities

1. **P0: Enforce cross-step state passing**
- Persist selected entity sets from step N and inject them into step N+1 prompts/inputs.
- If step 1 succeeded, never ask user for entities already derivable from that result.

2. **P0: Add synthesis-to-evidence consistency validation**
- Before rendering narrative, auto-check key claims against returned table rows (top/bottom entities, period bounds, rank statements).
- Block or rewrite contradictory claims.

3. **P0: Add derived-metric contract checks**
- Validate numerator/denominator semantic compatibility for computed deltas and percentages.
- Reject output when metric families are mixed (avg-ticket vs total-sales baseline).

4. **P1: Temporal intent contract**
- Normalize “last N months/weeks” into explicit date bounds once, enforce throughout all stages, and echo exact period in final answer.

5. **P1: Multi-objective query rendering**
- For questions requesting “highest X and highest Y,” produce multi-view evidence (dual rankings or split sections), not single-sort evidence.

6. **P2: Failure UX behavior**
- If one stage fails after partial success, return partial results with clear “incomplete” labeling instead of hard `Request Failed`.

## Suggested Acceptance Checks (for this starter set)

- Starter query suite should pass at **6/6 complete responses** with no clarification-required failure.
- No contradiction between narrative claims and top rows in primary evidence table.
- Period requests (`last month`, `last 6 months`, `last 8 weeks`) must match returned row date bounds exactly.
- Derived metric columns must pass unit compatibility checks.
