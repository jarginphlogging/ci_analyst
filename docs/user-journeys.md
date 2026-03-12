# User Journeys

Use this file for critical user journeys, expected visible behavior, and high-priority product regressions.

## Purpose

This document records the key user-facing flows and behaviors that matter in this product.

It should help humans and agents answer:
- what user journeys are critical
- what behaviors are expected
- what should be validated after changes
- what visible failures are high priority

This is especially important for product testing and Playwright-based validation.

---

## User journey philosophy

Not all flows matter equally.

Prioritize:
- primary user journeys
- flows tied to trust, correctness, and reliability
- flows likely to break due to state, async behavior, or UI orchestration
- flows that should be validated after meaningful frontend/product changes

Keep this document practical and agent-readable.

Repo-specific priorities:
- nontechnical users should be able to ask natural-language analytics questions without learning the data model
- streamed responsiveness matters because latency is part of the product experience
- evidence, assumptions, confidence, and trace surfaces matter because they support trust and auditability

---

## Critical user journeys

### Landing and workspace startup
- User goal:
  - open the product and reach a usable analytics workspace quickly
- Entry point:
  - `apps/web/src/app/page.tsx`
- Key steps:
  - home page loads
  - `AgentWorkspace` renders
  - starter prompts and session scaffolding appear
  - input area is ready for a question
- Expected visible behavior:
  - the main chat workspace renders without requiring hidden setup steps
  - the welcome message explains the supported domain at a high level
  - the page is interactive before any query is sent
- Important failure modes:
  - blank or partially rendered workspace
  - broken initial state
  - controls visible but not interactive
- Recommended validation:
  - load the page
  - verify starter prompts and the input surface render
  - check console and network for startup failures

### Main query and streamed chat flow
- User goal:
  - ask a natural-language analytics question and receive a streamed answer
- Entry point:
  - main input in `apps/web/src/components/agent-workspace.tsx`
- Key steps:
  - user submits a question
  - frontend posts to `/api/chat/stream`
  - assistant placeholder appears
  - stream status updates arrive
  - answer text streams incrementally
  - final structured response hydrates the UI
- Expected visible behavior:
  - the app reacts quickly after submit
  - loading/streaming state is visible and understandable
  - final content replaces placeholder state cleanly
  - no duplicate or contradictory assistant messages appear
- Important failure modes:
  - stalled stream
  - malformed partial response rendering
  - answer text and final structured content diverging
  - UI remaining in a loading state after the stream is done
- Recommended validation:
  - run one representative streamed query
  - verify status updates, incremental answer text, and final hydrated content
  - inspect console errors and failed network requests

### Results rendering and audit surfaces
- User goal:
  - understand the answer, supporting evidence, and confidence context
- Entry point:
  - final assistant response card in `AgentWorkspace`
- Key steps:
  - summary cards render
  - answer body renders
  - confidence and confidence reason render
  - assumptions render when present
  - evidence and data tables render
  - analysis trace remains accessible
- Expected visible behavior:
  - answer appears before or alongside supporting surfaces, not buried behind them
  - confidence, assumptions, and evidence stay coherent with the answer
  - data tables and evidence rows are inspectable
  - trace is visible enough for debugging/audit use without exposing private chain-of-thought
- Important failure modes:
  - final answer appears without usable evidence
  - confidence or assumptions contradict the visible result
  - evidence/table regions fail to render or render empty without explanation
  - trace shows an error while the response appears healthy
- Recommended validation:
  - verify a response with evidence, assumptions, and confidence
  - inspect a response with tabular output
  - confirm visible audit surfaces stay aligned with the answer

### Follow-up question flow
- User goal:
  - continue the analysis from the current conversation
- Entry point:
  - suggested questions and the main input after a prior response
- Key steps:
  - initial query completes
  - suggested follow-up questions render when available
  - user selects or types a follow-up
  - another streamed response begins without losing prior context
- Expected visible behavior:
  - follow-ups feel like continuation, not reset
  - prior conversation state remains visible
  - the new result reflects the continued analysis thread
- Important failure modes:
  - conversation appears to reset unexpectedly
  - suggested questions are missing, broken, or visibly inconsistent with the answer
  - follow-up response ignores visible prior context
- Recommended validation:
  - run a two-turn conversation
  - verify previous messages remain intact and the second answer looks context-aware

### Error and blocked flow
- User goal:
  - understand when the request failed, was blocked, or needs clarification
- Entry point:
  - `/api/chat/stream`, `/api/chat`, and response/error rendering in `AgentWorkspace`
- Key steps:
  - invalid or failing request occurs
  - proxy or orchestrator returns an explicit error
  - UI renders the error state
  - conversation stays usable for another attempt
- Expected visible behavior:
  - errors are explicit, not silent
  - blocked or invalid states do not masquerade as successful answers
  - the user can recover and ask another question
- Important failure modes:
  - silent failure
  - loading spinner never clears
  - partial answer shown as if complete
  - app becomes unusable after one failed attempt
- Recommended validation:
  - trigger at least one invalid or failing request path
  - verify explicit error messaging and post-error recoverability

### Evidence fallback table flow
- User goal:
  - still inspect returned evidence when richer table artifacts are absent
- Entry point:
  - final response rendering path in `AgentWorkspace`
- Key steps:
  - response contains evidence but no richer table artifact for that surface
  - fallback evidence table is synthesized from visible evidence rows
  - user can still inspect row-oriented support
- Expected visible behavior:
  - the user still sees a coherent table-like support surface
  - fallback behavior is visible and functional rather than silently dropping evidence
- Important failure modes:
  - evidence exists but no inspectable table appears
  - fallback output looks broken or contradictory
- Recommended validation:
  - verify one response that exercises the fallback evidence-table path

---

## High-value visible behaviors

- loading states are clear and accurate
- errors are explicit, not silent
- streamed responses transition cleanly into final structured content
- results appear in the expected region of the workspace
- confidence, assumptions, and evidence stay coherent with the answer
- controls remain usable after both success and failure
- follow-up suggestions extend the analysis without becoming prescriptive
- data tables and evidence remain inspectable when present
- navigation or layout does not strand the user away from the active conversation

---

## Common product failure modes

- broken startup state that leaves the workspace blank or half-rendered
- stale visible state after a failed or aborted request
- action succeeds but the visible UI does not update
- incorrect loading indicators or loading state that never clears
- silent console or network failures behind a misleading UI
- partial streamed response rendering without correct final hydration
- dead-end recovery after an error
- state desynchronization between answer text, evidence, confidence, and trace

Keep these focused on durable patterns, not one-off incidents.

---

## Validation guidance

When product behavior changes:
- validate the most relevant critical flows
- prefer targeted checks over broad wasteful runs
- inspect visible state, console errors, and important network failures
- distinguish app failures from test failures and environment failures

Use this doc together with:
- `docs/testing.md`
- `docs/learnings.md`
- `playwright-product-test`
