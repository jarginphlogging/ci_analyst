# Playwright Evaluation: Initial Six Starter Queries (Follow-up)

Date: 2026-03-06
Environment: local web + sandbox orchestrator (`http://localhost:3000`)
Method: live Playwright runs from the six starter cards, one query per fresh thread, with output review and expanded trace review after completion

Evaluation standard note:
- Explicit assumptions are desired behavior when they are visible, traceable, and consistent with the final answer.
- This review treats surfaced assumptions as a product strength unless they hide a material scope change, contradict the rendered answer, or expose that the answer should have been more heavily caveated.

Artifacts:
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q1.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q2.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q3.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q4.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q5.png`
- `/Users/joe/Code/ci_analyst/.tmp-playwright/review-current-q6.png`

## Executive Summary
- Starter-query latency is materially better for queries 1-5. Frontend stream completion ranged from about 22.8s to 36.9s.
- Several earlier concerns about assumption-making are softer under the correct product standard. Visible, auditable assumptions are a feature, not a flaw.
- Semantic trust is still the main weakness. Query 3 uses transaction proxies for a customer question, which is acceptable, but the proxy basis is still not prominent enough in the primary answer/UI and the final wording still reads too much like a customer-level claim.
- Comparison intent drift is still present. Query 4 and query 6 both plan as comparison answers but render ranked tables.
- Governance improved for query 5, but query 6 still uses prescriptive business language in `whyItMatters`.
- Query 6 is still not starter-quality. It took about 1m48s, retried SQL generation on step 3, and still ranked stores from mixed coverage windows.

## Query-by-Query Judgment

### 1) "Show me total sales last month."
Judgment: Good (A-)

What worked:
- Correct month window: November 2025.
- Fastest run in the set at about 22.8s network time.
- Clean single-step trace and simple answer.
- The interpretation of "last month" is explicit and audit-friendly, which is the right governed behavior.

Improvement needed:
- Confidence is still only `medium` for a straightforward scalar answer.
- KPI metadata is still wrong: sales metrics are labeled with unit `count` instead of currency.
- The only insight is still generic filler.

### 2) "Show me sales by state in descending order."
Judgment: Useful with weak scope visibility (B)

What worked:
- Ranking output is stable and trace is clean.
- Confidence basis is now explicit and deterministic.
- Defaulting a reasonable analysis window avoids unnecessary clarification and is the right product behavior.

Improvement needed:
- The chosen time window (`2024-01-01` through `2025-12-31`) should be surfaced more prominently in the top-level answer/UI.
- KPI metadata still labels sales as `count`.
- The first-view output is still a long ranked table rather than a compact summary with the table behind it.

### 3) "Show me new vs repeat customers by month for the last 6 months."
Judgment: Useful, but proxy transparency is still too weak (B-)

What worked:
- The 6-month window is correct.
- The chart label improved from `Customers` to `Transactions`.
- The answer now explicitly says "customer transactions" rather than pretending they are unique customers.
- Using transaction proxies for this kind of question is acceptable as long as the interpretation is visible and auditable.

Improvement needed:
- The proxy basis should be made more prominent in the top-level answer/UI, not mainly delegated to the assumptions section.
- `High` confidence is acceptable here if it is clearly scoped to the transaction-based interpretation. The current problem is that the answer and insights still read too much like customer-level findings while the assumptions reveal the evidence is proxy-based.
- The insights still reason about "customer segments" as if the evidence were customer-level rather than transaction-level proxy evidence.

### 4) "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?"
Judgment: Strong narrative, same contract bug (B)

What worked:
- The headline answer is concise and quantitatively clear.
- The SQL trace is fast and deterministic.
- The why-it-matters statement is policy-safe and grounded.

Improvement needed:
- The row payload still contains `transactions_pct_change: 0` while the answer correctly says transactions grew 13.4%. That exact contract bug remains.
- The planner and synthesis intent say `comparison`, but the rendered `tableConfig.style` is still `ranked`.
- KPI metadata still labels monetary metrics as `count`.

### 5) "For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?"
Judgment: Governance improved, analysis still shallow (B)

What worked:
- The earlier prescriptive `whyItMatters` problem is largely fixed.
- The answer clearly distinguishes average-ticket leadership from the relatively flat transaction-volume range.
- The trace now explicitly admits that week-over-week trend evidence was not available.
- The time-window interpretation is visible and auditable, which is appropriate.

Improvement needed:
- The result still does not solve the real multi-objective question. It ranks by average ticket and then comments on volume.
- The primary output is still 70 combinations, which is too heavy for a starter flow.
- There is still presentation drift: planner intent is `ranked`, but final `tableConfig.style` is `simple`.

### 6) "What were my top and bottom performing stores for 2025 ... and compare to the prior period?"
Judgment: Still not reliable enough (D+)

What worked:
- Runtime improved versus the baseline: about 1m48s instead of about 2m25s.
- The answer now explicitly acknowledges partial-year 2025 coverage.
- The trace makes the step-3 retry visible.

Improvement needed:
- The ranking is still invalid. Visible top rows span windows like `2025-04-01 to 2025-12-31`, `2025-03-01 to 2025-11-30`, and `2025-01-01 to 2025-09-30`, while bottom rows are single months. Raw spend cannot be ranked across those unequal windows.
- The assumptions admit the ranking reflects store-month combinations rather than annual store totals. That should block the answer, not sit as a caveat below it.
- `whyItMatters` is still prescriptive: it talks about informing resource allocation between acquisition and retention strategies.
- Presentation drift remains: presentation intent is `comparison`, but the final table config is `ranked`.
- The answer and insights still overreach. In particular, "Repeat Spend Declined Sharply in 2025" is not a trustworthy conclusion from this evidence package.
- The time-window story is internally inconsistent: the assumptions say 2025 spans January through August, but the visible ranked rows run through December 2025.

## Comparison To `playwright_initial_six_feedback_2026-03-06.md`

### Specific Improvements
- Query 1 latency improved substantially. In this follow-up run, network completion was about 22.8s and synthesis was about 7.8s, versus the earlier note that synthesis alone took about 41.7s.
- Query 3 improved its visual labeling. The chart now uses `Transactions` on the y-axis instead of `Customers`.
- Query 5 improved its governed narrative. The earlier staffing/inventory/promotional language is gone.
- Query 6 improved its total runtime from about 2m25s to about 1m48s and now explicitly caveats partial-year coverage.
- Queries 1 and 5 both look better under the correct evaluation standard because their surfaced assumptions are visible and audit-friendly rather than hidden.
- Query 3 also looks better under the correct standard in one important respect: using transaction proxies is not itself a defect when the choice is surfaced.

### Specific Regressions
- Query 3 wording alignment is worse. The proxy choice is acceptable, but the answer still reads too much like a customer-level claim even though the assumptions say the evidence is transaction-based.
- Query 2 is more assertive without making the chosen default time window prominent enough in the rendered answer.
- Query 6 added new unsupported analytical claims. "Repeat Spend Declined Sharply in 2025" is a stronger and less defensible conclusion than the earlier caveated version.
- Query 6 now has an additional internal inconsistency: the assumptions say January through August 2025, but the ranked rows shown in the UI extend through December 2025.

### Issues Still Unaddressed
- Time-scope visibility in the top-level answer/UI when the system applies a default analysis window.
- KPI/unit metadata labeling currency metrics as `count`.
- Query 4's `transactions_pct_change: 0` payload bug.
- Final payload/UI drifting away from planned comparison intent.
- Proxy transparency and confidence calibration when the system answers customer questions with transaction-based measures.
- Invalid mixed-window store ranking logic in query 6.
- Starter-query suitability for query 6.

## Prioritized Improvements
1. Add deterministic metric-lineage and unit checks before synthesis.
Block currency metrics from surfacing as `count`, and require the UI/answer wording to make proxy-based interpretations obvious when the retrieved measures are transaction-based.

2. Tie confidence and claim strength to proxy detection.
Visible assumptions are good. Confidence should reflect confidence in the answer under the stated interpretation, but the final answer and insights must make that proxy-based interpretation unmistakable.

3. Enforce planned presentation intent in the final payload.
If planner/synthesis intent is `comparison`, final `tableConfig.style` should not downgrade to `ranked`.

4. Block rankings over unequal coverage windows.
For store-performance questions, require aligned windows or normalized metrics before ranking.

5. Add governed-language linting to `whyItMatters` and insights.
Query 5 improved, but query 6 still crosses the policy line.

6. Fix the direct payload contract bug in query 4.
The table row and narrative cannot disagree on percentage change.

7. Rework or replace the store-comparison starter.
If the path still needs retries and nearly two minutes, it is not an acceptable starter in its current form.
