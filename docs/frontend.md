# Frontend

Use this file for the structure, runtime behavior, data flow, and change points of the web application frontend.

## Purpose

This document explains how the frontend works in this repository.

It should help a new engineer answer:
- what the web app owns
- which files matter most
- how the UI talks to the backend
- how streamed responses are rendered
- where user-visible state is stored
- where to make changes for specific product behaviors

This is durable frontend architecture documentation.
It is not a scratchpad or a one-off implementation log.

---

## Frontend overview

The frontend is a Next.js app in `apps/web`.

Its job is not to implement analytics logic. Its job is to:
- collect user questions
- proxy requests to the orchestrator
- render streamed and final responses
- surface evidence, trace, assumptions, and follow-up questions
- give users access to returned tabular data

The frontend is intentionally thin in terms of business logic. It does a meaningful amount of presentation shaping, but it should not become the place where semantic meaning, metric interpretation, or backend orchestration rules are invented.

Primary frontend responsibilities:
- show the main conversational workspace
- manage the current client-side thread state
- read NDJSON stream events and update the in-flight assistant message
- render response sub-surfaces:
  - summary cards
  - why-it-matters panel
  - evidence/visual table surface
  - retrieved data explorer
  - analysis trace
  - assumptions
  - suggested next questions
- expose lightweight environment status to the user

Primary non-responsibilities:
- do not decide business semantics
- do not generate SQL
- do not reinterpret the backend trace into hidden logic
- do not silently conceal backend failures as successful answers

---

## Frontend boundary

The frontend boundary is mostly:
- `apps/web/src/app`
- `apps/web/src/components`
- `apps/web/src/lib`

The frontend depends on:
- backend response contracts from `@ci/contracts`
- orchestrator HTTP routes exposed through the Next.js API proxy layer

The frontend does not directly talk to databases or provider SDKs.

---

## Frontend runtime layout

### App shell

Key files:
- `apps/web/src/app/layout.tsx`
- `apps/web/src/app/page.tsx`
- `apps/web/src/app/globals.css`

What they do:
- `layout.tsx` defines the shared app shell
- `page.tsx` mounts the main `AgentWorkspace`
- `globals.css` provides global styling and animation primitives used by the workspace

Important detail:
- `page.tsx` currently passes `initialEnvironment="Sandbox"` into the workspace and the workspace later resolves the current environment via `/api/system-status`

### Main workspace

Key file:
- `apps/web/src/components/agent-workspace.tsx`

This is the main frontend controller component.

It owns:
- the conversation transcript displayed in the UI
- the current input text
- loading/streaming state
- starter-question UI
- left and right pane visibility
- session ID generation and reset
- per-message feedback state
- environment label state
- orchestration of request submission and stream consumption

If you want to change most visible product behavior, this file is usually the first place to inspect.

---

## API proxy layer

The frontend has a small server-side proxy surface under `apps/web/src/app/api`.

### `apps/web/src/app/api/chat/route.ts`

Role:
- non-streaming turn proxy

Behavior:
- validates the incoming request with `chatTurnRequestSchema`
- rejects malformed payloads early with `400`
- forwards valid requests to `${ORCHESTRATOR_URL}/v1/chat/turn`
- returns the upstream body and status largely unchanged

Use this route when:
- you want one-shot request/response behavior
- a local check or eval wants the non-stream contract

### `apps/web/src/app/api/chat/stream/route.ts`

Role:
- streaming turn proxy

Behavior:
- validates the request with `chatTurnRequestSchema`
- forwards it to `${ORCHESTRATOR_URL}/v1/chat/stream`
- preserves an NDJSON stream response
- emits NDJSON error events when request validation or upstream access fails
- returns `204` on abort

Important detail:
- the route always responds with NDJSON-oriented headers when it is serving stream events

This route is the main product path used by the conversation UI.

### `apps/web/src/app/api/system-status/route.ts`

Role:
- lightweight environment badge source

Behavior:
- if the web backend mode is not orchestrator or no orchestrator URL is configured, it returns a default environment
- otherwise it fetches `/health` from the orchestrator
- it maps provider mode into the UI labels `Sandbox` or `Production`

Important limitation:
- this route is intentionally shallow; it is not a general health dashboard

---

## Environment and server configuration

Key file:
- `apps/web/src/lib/server-env.ts`

This file resolves the minimal server-side environment used by the frontend API routes.

Current fields:
- `ORCHESTRATOR_URL`
- `WEB_BACKEND_MODE`

Current behavior:
- only `orchestrator` is recognized as a valid backend mode
- unknown or missing `WEB_BACKEND_MODE` normalizes to `orchestrator`

What this means:
- the frontend assumes the orchestrator is the system of record
- switching backend behavior should happen through explicit server-env configuration, not ad hoc fetch rewrites in client components

---

## Shared data contract boundary

The frontend should treat the shared contract package as the source of truth for payload shapes crossing the web/backend boundary.

Key file:
- `packages/contracts/src/index.ts`

Important shared schemas:
- `chatTurnRequestSchema`
- `chatStreamEventSchema`
- `agentResponseSchema`
- `chatTurnResponseSchema`

Important response fields the frontend actively uses:
- `summary.answer`
- `summary.confidence`
- `summary.whyItMatters`
- `summary.summaryCards`
- `summary.insights`
- `summary.suggestedQuestions`
- `summary.assumptions`
- `summary.periodStart`
- `summary.periodEnd`
- `summary.periodLabel`
- `visualization.chartConfig`
- `visualization.tableConfig`
- `visualization.primaryVisual`
- `data.dataTables`
- `data.evidence`
- `data.comparisons`
- `audit.artifacts`
- `audit.facts`
- `trace`

If a backend field changes shape or meaning:
- update the contract first
- then update frontend rendering code
- then update any affected tests and docs

Do not rely on untyped ad hoc payload assumptions inside components.

---

## Main user-facing flow

The main path through the frontend is:

1. `apps/web/src/app/page.tsx` renders `AgentWorkspace`
2. `AgentWorkspace` initializes local UI state and a welcome message
3. the user enters a question or taps a starter question
4. `submitQuery` in `AgentWorkspace` creates:
   - a new user message
   - an empty streaming assistant message
5. the component posts to `/api/chat/stream`
6. the route proxies to the orchestrator stream endpoint
7. `readNdjsonStream` parses each NDJSON line into a typed stream event
8. `AgentWorkspace` updates the in-flight assistant message based on each event type
9. once the final `response` event arrives, the assistant message gains the full structured `response`
10. the UI renders the full response surfaces from that payload
11. a final `done` event stops streaming state

The frontend is therefore event-driven during execution and contract-driven after the final payload arrives.

---

## Client-side conversation state

`AgentWorkspace` owns the visible transcript and most interaction state.

Important state variables:
- `input`
  - current composer contents
- `isLoading`
  - whether a request is currently in flight
- `environment`
  - `Sandbox` or `Production`
- `sessionId`
  - client-generated thread identity used in requests
- `messages`
  - ordered conversation transcript
- `feedbackByMessageId`
  - local user feedback state per response
- `isLeftPaneVisible`
- `isRightPaneVisible`
- `areStarterPromptsExpanded`

Important refs:
- `inFlightRequestRef`
  - stores the active `AbortController`
  - stores the in-flight assistant message ID
  - stores the request start time for runtime display

Important behavior:
- a new thread resets the session ID, input, feedback, and transcript
- stopping a request aborts the fetch and converts the streaming message into a stopped state
- environment is fetched once on mount from `/api/system-status`

---

## Stream parsing and event handling

Key file:
- `apps/web/src/lib/stream.ts`

This file does the low-level NDJSON stream work for the frontend.

Important functions:
- `parseNdjsonChunk`
  - splits buffered stream text by newline
  - preserves trailing partial data in `carry`
  - parses each full line as JSON
- `validateStreamEvent`
  - validates events against `chatStreamEventSchema`
  - permits a narrow permissive validation path for minimal stream events
- `readNdjsonStream`
  - reads bytes from `ReadableStream<Uint8Array>`
  - decodes chunks
  - calls the caller’s event handler per parsed event

Current event types:
- `status`
- `answer_delta`
- `response`
- `done`
- `error`

How `AgentWorkspace` uses them:
- `status`
  - appended to `statusUpdates`
- `answer_delta`
  - appended to the streaming assistant text
- `response`
  - replaces draft text with the final structured response answer
  - stores the full structured response payload on the assistant message
- `error`
  - marks the message as failed
- `done`
  - clears streaming state

This is the most important frontend/backend streaming contract boundary.

If stream behavior changes, inspect:
- `apps/web/src/lib/stream.ts`
- `apps/web/src/components/agent-workspace.tsx`
- `packages/contracts/src/index.ts`

---

## Major rendered surfaces

### Conversation workspace

Key file:
- `apps/web/src/components/agent-workspace.tsx`

Visible regions:
- left rail
  - product title
  - environment badge
  - simple session list / compose-new-thread control
- center workspace
  - message transcript
  - starter prompts
  - composer
- right rail
  - latest-response summary and next-action context

The transcript is the dominant product surface.

Each assistant message may render:
- the answer text
- streaming progress
- confidence badge
- why-it-matters panel
- summary cards
- evidence/visual table surface
- priority insights
- retrieved data
- analysis trace
- assumptions
- suggested next questions

### Evidence / visual surface

Key file:
- `apps/web/src/components/evidence-table.tsx`

What it owns:
- choosing between a chart panel, a comparison panel, or a table panel
- interpreting `visualization.chartConfig`, `visualization.tableConfig`, `visualization.primaryVisual`, `data.dataTables`, and `data.comparisons`
- rendering the first returned data table as the main evidence/visual surface when appropriate

Important behavior:
- if no table exists, it renders a “No tabular output” state
- if semantic comparison data is available, it may prefer a comparison panel
- if a chart is viable and the table/config combination supports it, it renders a chart
- otherwise it falls back to table-oriented display

This file is one of the highest-risk UI files because it translates backend shape into visible analysis display.

### Retrieved data explorer

Key file:
- `apps/web/src/components/data-explorer.tsx`

What it owns:
- selecting among returned data tables
- row/column viewing
- CSV export
- JSON export
- optional source SQL expansion

Important behavior:
- this is an inspection surface, not the main narrative surface
- it renders “No tabular artifacts were returned” when no data tables exist

### Analysis trace

Key file:
- `apps/web/src/components/analysis-trace.tsx`

What it owns:
- rendering backend trace steps
- rendering stage input/output payloads
- grouping SQL-stage LLM exchanges by step when possible
- hiding sensitive/raw prompt payload internals like `llmPrompts` and `llmResponses` from generic JSON rendering while still exposing structured trace sections

Important behavior:
- this is the governed transparency surface
- it should expose explainability without leaking private raw chain-of-thought as a simple dump

If trace UX changes, validate carefully against:
- auditability expectations
- readability for nontechnical users
- accidental exposure of internals

---

## Message shape inside the UI

The frontend keeps its own message objects in `apps/web/src/lib/types.ts` and `agent-workspace.tsx`.

Conceptually, each visible transcript entry has:
- an ID
- a role
- text
- creation time
- optional structured `response`
- optional streaming flags / status updates
- optional timing data

The important distinction:
- user messages are simple text entries
- assistant messages may begin as streaming placeholders and later become full structured result containers

That dual state is why many UI bugs show up as:
- empty assistant bubbles
- streaming never resolving
- final response arriving but not hydrating all sub-surfaces

---

## Derived frontend logic

The frontend intentionally does some display-oriented derivation.

Examples inside `AgentWorkspace`:
- summary-card rendering from `summary.summaryCards`
- label normalization and formatting
- period-label inference from SQL or returned tables
- runtime label formatting
- latest-response snapshot metadata
- renderable table derivation for `DataExplorer`

This logic is acceptable when it is:
- display-oriented
- bounded
- reversible
- not redefining backend semantics

This logic becomes risky when it starts:
- inventing business meaning
- contradicting backend presentation intent
- hiding missing data with made-up substitutes

If a change feels semantic rather than presentational, it probably belongs in the backend.

---

## Error handling and degraded states

Current frontend error behavior includes:
- malformed input rejected by API routes
- unavailable orchestrator surfaced as request failure
- stream errors converted into visible assistant-message failures
- request abort exposed as stopped analysis
- missing returned tables surfaced as explicit empty states in the evidence or data-explorer panels

Important rule:
- failed requests should remain visibly failed
- blocked or invalid backend states should not masquerade as successful analytics answers

Frontend failure hotspots:
- stream proxy route returning malformed NDJSON
- `readNdjsonStream` receiving partial or invalid payloads
- `AgentWorkspace` not finalizing a streaming message after `done`
- response subcomponents assuming fields are present when they are optional

---

## Styling and visual system

The frontend uses:
- Next.js app router
- React client components for the main workspace
- Tailwind-style utility classes
- custom gradients, rounded containers, and visual hierarchy in component markup

The visual language is intentionally not a generic chatbot.

Current UI direction:
- dark control/navigation rail
- lighter analysis surface in the center
- highly visible cards and evidence surfaces
- strong use of spacing, borders, and gradients for layered product feel

If you change styling:
- preserve the “decision cockpit” direction from `docs/frontend-ux-spec.md`
- avoid collapsing the interface into a plain generic chat layout

---

## Tests that matter for the frontend

Relevant files:
- `apps/web/src/lib/stream.test.ts`
- `apps/web/src/components/evidence-table.test.tsx`

These tests currently focus on:
- stream parsing behavior
- evidence-table rendering behavior

Frontend regressions that deserve special attention:
- stream event parsing
- message hydration after streaming
- trace rendering
- table/chart switching logic
- optional-field handling

Broader validation guidance lives in:
- `docs/testing.md`
- `docs/user-journeys.md`

---

## Common change scenarios

### Change the main layout or transcript behavior

Start with:
- `apps/web/src/components/agent-workspace.tsx`

### Change stream parsing or event behavior

Start with:
- `apps/web/src/lib/stream.ts`
- `packages/contracts/src/index.ts`
- `apps/web/src/app/api/chat/stream/route.ts`

### Change how evidence, charts, or tables render

Start with:
- `apps/web/src/components/evidence-table.tsx`

### Change trace visibility or explainability UI

Start with:
- `apps/web/src/components/analysis-trace.tsx`

### Change retrieved-data browsing or exports

Start with:
- `apps/web/src/components/data-explorer.tsx`

### Change request validation or proxy behavior

Start with:
- `apps/web/src/app/api/chat/route.ts`
- `apps/web/src/app/api/chat/stream/route.ts`
- `apps/web/src/lib/server-env.ts`

---

## Risk areas

### Streaming lifecycle

What can go wrong:
- `status`, `answer_delta`, `response`, and `done` events arrive in a shape or order the UI mishandles
- abort and error paths leave the UI in an inconsistent loading state

What to validate:
- one successful streamed flow
- one failed stream flow
- one stopped/aborted flow

### Contract drift

What can go wrong:
- backend fields change and the UI silently stops rendering sections
- optional fields are assumed to be present

What to validate:
- compile/runtime behavior
- rendered response sections with realistic payloads

### Presentational logic becoming semantic logic

What can go wrong:
- the UI begins redefining business meaning instead of displaying backend outputs

What to validate:
- changes still feel display-oriented
- backend remains the semantic authority

### Evidence and trace trust surface

What can go wrong:
- evidence disappears even when data exists
- trace becomes noisy, misleading, or exposes the wrong internals

What to validate:
- one normal answer with evidence
- one answer with meaningful trace inspection
- one failure path that still explains what happened

---

## Where to look before changing the frontend

Read these first:
- `docs/frontend-ux-spec.md`
- `docs/user-journeys.md`
- `docs/api-contracts.md`
- `docs/testing.md`

Then inspect code in this order:
- `apps/web/src/components/agent-workspace.tsx`
- relevant subcomponent under `apps/web/src/components/`
- API route under `apps/web/src/app/api/`
- shared contract in `packages/contracts/src/index.ts`

---

## Update rule

Update this document when:
- the main frontend entrypoint changes
- the proxy/request model changes
- the primary rendered surfaces change materially
- streamed message handling changes materially
- the division of responsibility between frontend and backend changes

Do not update this doc for small copy edits or purely cosmetic one-off tweaks unless they change durable frontend behavior.
