# Playwright Evaluation: Initial Six Starter Queries

Date: 2026-03-06
Environment: local web + sandbox orchestrator (`http://localhost:3000`)
Method: live Playwright runs, one starter query at a time, with output and trace review

Artifacts:
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q1.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q2.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q3.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q4.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q5.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-2026-03-06-q6.png`

## Executive Summary
- Overall quality is still strong for simple scalar and clean period-comparison questions.
- The biggest remaining problem is semantic trust: several answers still narrate transaction-based metrics as customer metrics, or make comparison claims despite an `insufficient` evidence layer.
- The sixth starter is not starter-quality yet. In today’s run it took about 2 minutes 25 seconds, required SQL refinement on step 3, and still returned a ranking built from mismatched coverage windows.

## Query-by-Query Judgment

### 1) "Show me total sales last month."
Judgment: Good (A-)

What worked:
- Clear answer, correct month window, and clean trace.
- Output is concise and easy to audit from the table and trace.

Improvement needed:
- The only insight is still generic filler.
- Runtime is too high for a one-row starter query: synthesis alone took about 41.7s in the trace.

### 2) "Show me sales by state in descending order."
Judgment: Useful but scope-defaulted (B)

What worked:
- Ranked table is coherent and the top/bottom narrative is readable.
- The trace is clean and deterministic.

Improvement needed:
- The app silently defaults to a two-year window (`Jan 2024–Dec 2025`) even though the user did not ask for one.
- `evidenceStatus` is still `insufficient`, but the answer and insights are assertive anyway.
- The first-view UX is too heavy: 30 ranked rows before any compact summary block.

### 3) "Show me new vs repeat customers by month for the last 6 months."
Judgment: Semantically wrong (C)

What worked:
- The 6-month window is correct and the chartable output is stable.
- The trace shows a clean recovery from the earlier off-by-one month issue.

Improvement needed:
- The response still calls these "customers" while the assumptions admit the figures are transaction counts, not unique customers.
- `chartConfig.yLabel` is "Customers" even though the evidence is transaction-based.
- The answer makes stronger retention claims than the evidence supports; `evidenceStatus` is `insufficient`.

### 4) "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?"
Judgment: Strong answer, but one serious payload inconsistency (B+)

What worked:
- The top-line narrative is excellent: concise, quantitative, and policy-safe.
- Comparison objects are well formed and confidence is appropriately high.

Improvement needed:
- The returned row payload shows `transactions_pct_change: 0`, while the comparison object and answer both say transactions grew 13.4%. That is a concrete data contract bug.
- The planner chooses comparison intent, but the synthesized table config still comes back as `ranked` instead of `comparison`.

### 5) "For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?"
Judgment: Mixed and policy-violating (C+)

What worked:
- The system correctly identifies that Friday dominates the top average-ticket ranks.
- The answer explicitly admits it cannot identify one combination that optimizes both objectives.

Improvement needed:
- `whyItMatters` is still prescriptive: it says the result can inform staffing, inventory allocation, and promotional timing. That violates the governed-product rule.
- The system still lacks a true multi-objective ranking. It mostly ranks average ticket and then gestures at transaction volume.
- The primary output remains too wide and too detailed for a starter flow: 70 combinations with a weak summary layer.

### 6) "What were my top and bottom performing stores for 2025 ... and compare to prior period?"
Judgment: Not reliable enough (D+)

What worked:
- The planner decomposes the question into three sensible steps.
- The final narrative is more complete than the March 5 run and the trace exposes the long SQL stage.

Improvement needed:
- The top/bottom ranking is still built from unequal coverage windows. In the visible table, "top" stores span windows like `2025-04-01 to 2025-12-31`, `2025-03-01 to 2025-11-30`, and `2025-01-01 to 2025-09-30`, while bottom stores include single-month windows. That makes the ranking invalid.
- The answer now claims prior-period customer mix was "relatively stable," but the trace still says the evidence layer could not derive period-over-period comparisons. The narrative is overreaching.
- The trace showed `Refining data retrieval for step 3/3 (attempt 2/3)` and total runtime was about 2m25s. That is far too slow and fragile for a starter query.
- Behavior is unstable across runs: the March 5 run caveated that same-store prior-period comparison was not possible, while today’s run asserted a stable comparison. That suggests prompt or synthesis instability rather than a trustworthy deterministic outcome.

## Cross-Cutting Findings
1. Semantic label integrity is still the top issue.
The system continues to narrate transaction metrics as customer metrics in query 3, and parts of query 6 blur transaction mix with customer mix.

2. Evidence gating is too weak.
Queries 2, 3, 5, and 6 all had `evidenceStatus: insufficient`, yet the answers still delivered fairly strong synthesized claims.

3. Starter-query latency is too high.
Even the clean cases are slower than they should be, and query 6 is decisively outside acceptable starter UX.

4. Presentation intent is not consistently honored.
Query 4 and query 6 both drift away from the planner’s comparison intent in the final payload/UI.

5. Governed narrative policy is still not fully enforced.
Query 5 still contains action-oriented business language.

## Prioritized Improvements
1. Add deterministic semantic-fidelity checks between metric lineage and narration.
Block any response that labels transaction-based measures as customers, households, or people.

2. Gate synthesis claims on evidence sufficiency.
If `evidenceStatus` is `insufficient`, require visibly caveated wording and prohibit stable-comparison claims unless backed by comparison objects.

3. Enforce comparability before ranking stores.
For top/bottom store questions, require aligned coverage windows or normalize the metric before ranking. Do not rank mixed-duration stores on raw spend.

4. Fix comparison payload consistency.
Query 4 exposes a direct mismatch between table payload and comparison narrative. That should be caught before response emission.

5. Add a governed-language rewrite pass for `whyItMatters` and insights.
Specifically reject prescriptive wording like staffing, allocation, timing, or optimization advice.

6. Rework the complex-store starter path.
If it needs three steps, retries, and 2+ minutes, it should not be a starter query in its current form.
