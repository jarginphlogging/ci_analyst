# Playwright Evaluation: Initial Six Starter Queries

Date: 2026-03-05
Environment: local web + sandbox orchestrator (`http://localhost:3000`)
Method: automated Playwright execution, one query at a time, with captured transcripts/screenshots.

Artifacts:
- `/Users/joe/Code/ci_analyst/.tmp-playwright/starter-query-results.json`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/single-q2.json`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/single-q4c.json`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/single-q5b.json`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/single-q6b.json`

## Executive Summary
- Overall quality: strong on numeric correctness and structure for straightforward queries.
- Main gaps: temporal scope defaults are inconsistent/implicit, customer-vs-transaction semantics are sometimes mismatched, and complex multi-step queries can fail or degrade.
- Compliance risk: at least one narrative included action-oriented phrasing (should be strictly descriptive per policy).

## Query-by-Query Judgment

### 1) "Show me total sales last month."
Judgment: Good (A-)
What worked:
- Clear direct answer (`$98.4M`), clear period, confidence, assumptions, and follow-ups.
- Output is concise and auditable.
Improvement needed:
- Insight quality is generic ("Primary data is ready") instead of a meaningful data-derived observation.

### 2) "Show me sales by state in descending order."
Judgment: Good with scope ambiguity (B+)
What worked:
- Correct ranked table and coherent top/bottom narrative.
- Useful concentration insight and totals.
Improvement needed:
- Time scope defaulted to "2024–2025" without user request; this should be explicit in the headline or clarified before execution.
- Add a compact distribution summary (e.g., top 5 share, median state) before full 30-row table.

### 3) "Show me new vs repeat customers by month for the last 6 months."
Judgment: Mixed semantic correctness (B)
What worked:
- Good trend framing and stable repeat-share insight.
- Proper time window and helpful follow-ups.
Improvement needed:
- Uses transaction counts while phrased as customer counts; assumptions disclose this, but primary narrative still reads as true customer counts.
- Should either:
  - calculate true distinct customers, or
  - rename output everywhere to "new vs repeat transactions".

### 4) "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?"
Judgment: Strong (A)
What worked:
- Excellent metric triad with clean YoY deltas.
- Why-it-matters statement is evidence-backed and non-speculative.
- Comparison table is compact and decision-useful.
Improvement needed:
- Minor: include explicit provenance pointers in UI card layer (step/time window badges) to improve auditability visibility.

### 5) "For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?"
Judgment: Useful but overloaded and policy-risky phrasing (B-)
What worked:
- Correctly surfaces two winners: highest avg ticket vs highest transaction volume.
- Insight about divergence of value leader vs volume leader is strong.
Improvement needed:
- Narrative includes action-oriented wording ("informing staffing, inventory, and promotional timing decisions"). This should be neutral/descriptive in governed mode.
- Table is too heavy (70 rows) for primary output; lead with top-N slices for each metric and keep full table behind expand/export.

### 6) "What were my top and bottom performing stores for 2025 ... and compare to prior period?"
Judgment: Medium quality, high comparability risk (C+)
What worked:
- Returned top/bottom stores and customer mix; included caveat when prior-period comparability failed.
- Explicit assumptions called out data-coverage limitations.
Improvement needed:
- Store ranking appears to mix unequal coverage windows (some monthly slices vs near full-year), which can distort top/bottom results.
- Prior-period comparison should be re-planned automatically when entity alignment fails (same store IDs across periods) rather than stopping at caveat.
- Initial run intermittently failed with `generation_provider_error` before succeeding on rerun, indicating robustness issues for complex prompts.

## Prioritized Improvements
1. Enforce semantic label integrity
- If metric is transaction-based, output must not call it "customers".
- Add deterministic post-check to block mismatched terminology.

2. Make temporal scope explicit and deterministic
- When user omits period, surface selected default period in answer headline and assumptions immediately.
- Prefer explicit clarification for ambiguous ranking queries when multiple valid periods exist.

3. Strengthen complex-query reliability
- Add automatic retry/escalation path on SQL generation failure with structured fallback decomposition.
- Detect entity misalignment across periods and auto-run alignment query instead of returning a partial caveat.

4. Tighten governed narrative policy
- Add synthesis guardrail to reject action-recommendation phrasing and rewrite to neutral descriptive language.

5. Improve first-view signal density
- For large tables, show compact "top findings" blocks first and keep full raw ranking behind expand/export.

