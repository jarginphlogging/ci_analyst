# I Am The Message: My Journey Through The Backend

I start life as a user question sent to the orchestrator API.  
By the time I leave, I have turned into a governed analytics response with trace steps, evidence tables, and suggested follow-ups.

This is my exact journey in the current backend implementation.

## 1) My Passport (What I Look Like On Arrival)

I arrive as `ChatTurnRequest` in `apps/orchestrator/app/models.py`:

- `sessionId` (optional UUID)
- `message` (required text)
- `role` (optional string)
- `explicitFilters` (optional dictionary)

I can enter through one of two doors in `apps/orchestrator/app/main.py`:

- `POST /v1/chat/turn` (single JSON response)
- `POST /v1/chat/stream` (NDJSON event stream)

There is also a health probe:

- `GET /health`

## 2) Who Handles Me Depends On Mode

In `apps/orchestrator/app/services/dependencies.py`, the backend decides my execution engine using `PROVIDER_MODE`:

- `mock`: deterministic mock pipeline, no real providers.
- `sandbox`: real orchestration stages + Anthropic + local Cortex-compatible service + local SQLite.
- `prod`: real orchestration stages + Azure OpenAI + Snowflake Cortex SQL adapter.

Provider wiring lives in:

- `apps/orchestrator/app/providers/factory.py`

## 3) First Stop: Session Memory

Inside `apps/orchestrator/app/services/orchestrator.py`, I am attached to session context:

1. My `sessionId` is resolved (or `"anonymous"`).
2. Prior history for prompts is capped to last 8 messages.
3. Stored session history is capped to last 12 messages.

This memory is in-process only. If the service restarts, memory resets.

## 4) If I Took `/v1/chat/turn` (Non-Streaming Path)

My route is:

1. `run_turn(...)` starts.
2. I pass through pipeline execution:
   - route classification,
   - plan generation,
   - SQL generation/execution,
   - validation.
3. Final response is synthesized.
4. Validation checks are injected into trace step `t3`.
5. Route and session-depth assumptions are appended.
6. I leave as `TurnResult` with:
   - `turnId`,
   - `createdAt`,
   - `response` (`AgentResponse`).

## 5) If I Took `/v1/chat/stream` (Streaming Path)

My route is similar, but I leave in phases:

1. `status` events while pipeline progresses.
2. Draft `response` event (`phase="draft"`) from deterministic fast synthesis.
3. Multiple `answer_delta` events (token-like chunks for UI animation).
4. Final `response` event (`phase="final"`).
5. `done`.

If anything fails:

- `error` event is emitted,
- then `done`.

In `mock` mode only, event pacing delays are applied:

- `MOCK_STREAM_STATUS_DELAY_MS`
- `MOCK_STREAM_TOKEN_DELAY_MS`
- `MOCK_STREAM_RESPONSE_DELAY_MS`

## 6) My Real Pipeline Stages (Sandbox + Prod)

When not in pure mock mode, I go through 4 concrete stages.

### Stage A: Route + Plan (`PlannerStage`)

Files:

- `apps/orchestrator/app/services/stages/planner_stage.py`
- `apps/orchestrator/app/prompts/templates.py`

What happens to me:

1. Route classifier prompt tries to classify me as:
   - `fast_path`, or
   - `deep_path`.
2. If LLM classification fails or is malformed, heuristic fallback classifies by keywords.
3. Plan prompt generates bounded steps.
4. Step count is clipped by config:
   - `REAL_FAST_PLAN_STEPS` (default 2)
   - `REAL_DEEP_PLAN_STEPS` (default 4)
5. If plan parsing fails, deterministic fallback plan is used.

### Stage B: SQL (`SqlExecutionStage`)

File:

- `apps/orchestrator/app/services/stages/sql_stage.py`

What happens to me:

1. For each plan step, backend tries to get SQL:
   - via analyst service first (if available; sandbox),
   - else via LLM SQL prompt.
2. SQL is always passed through guardrails.
3. SQL executes.
4. If SQL execution fails, fallback SQL is attempted.
5. Results are normalized into JSON-safe rows.

Optional parallel execution:

- enabled only when analyst service is not used,
- controlled by:
  - `REAL_ENABLE_PARALLEL_SQL` (default `false`)
  - `REAL_MAX_PARALLEL_QUERIES` (default `3`)
- final ordering is restored to plan-step order.

Deterministic repair can run after SQL:

1. period-comparison shape repair,
2. period-context repair,
3. grain repair (store/state/channel/time mismatch).

These repairs append assumptions that explain what was auto-corrected.

### Stage C: Validation (`ValidationStage`)

File:

- `apps/orchestrator/app/services/stages/validation_stage.py`

My SQL outputs are checked for:

1. at least one SQL step executed,
2. total rows > 0,
3. no result above semantic model max row policy,
4. sampled null-rate < 95%.

If validation fails, orchestration stops with `Result validation failed.`

### Stage D: Synthesis (`SynthesisStage`)

File:

- `apps/orchestrator/app/services/stages/synthesis_stage.py`

I become final response material in two layers:

1. Deterministic layer:
   - evidence rows,
   - analysis artifacts,
   - metric points,
   - exportable data tables.
2. Optional LLM narrative layer:
   - answer,
   - why-it-matters,
   - insights,
   - suggested questions,
   - assumptions.

If LLM output is missing/invalid, deterministic fallback narrative is used.

Artifact and table profiling logic:

- `apps/orchestrator/app/services/table_analysis.py`

## 7) My Security Checkpoints (SQL Governance)

Before any SQL runs, `guard_sql(...)` in `apps/orchestrator/app/services/sql_guardrails.py` enforces:

1. read-only start (`SELECT`/`WITH`),
2. block write/admin statements (`insert`, `update`, `delete`, `drop`, etc.),
3. allowlisted table references only (semantic model),
4. restricted-column blocking,
5. automatic row limit policy (`LIMIT` add or clamp).

This means I cannot become arbitrary SQL execution.

## 8) My Semantic Contract (What Data I Can Touch)

Semantic model is loaded by:

- `apps/orchestrator/app/services/semantic_model.py`

Default model file:

- `packages/semantic-model/models/banking-core.v1.json`

It controls:

1. allowed tables,
2. dimensions and metrics exposed to prompts,
3. restricted columns,
4. default and max row limits.

Runtime override:

- `SEMANTIC_MODEL_PATH=/absolute/path/to/model.json`

## 9) My LLM Call Budget

In one query, my typical LLM calls are:

- `mock`: 0
- `prod`: `steps + 3`
- `sandbox`: usually `steps + 3` total (orchestrator + sandbox analyst flow)

Default:

- fast path (2 steps): ~5 calls
- deep path (4 steps): ~7 calls

No automatic LLM retries are built in for these stages; fallback behavior is deterministic.

## 10) My Sandbox Side Quest (When `PROVIDER_MODE=sandbox`)

The sandbox analyst service is:

- `apps/orchestrator/app/sandbox/cortex_service.py`

Backed by local SQLite:

- `apps/orchestrator/app/sandbox/sqlite_store.py`

The service can:

1. accept NL messages (`/message`),
2. generate SQL with Anthropic,
3. ask clarification for vague questions,
4. execute guarded SQL locally,
5. return rows + light response + assumptions,
6. keep short conversation memory by `conversationId`.

Seeded tables include:

- `cia_sales_insights_cortex`
- `cia_household_insights_cortex`

## 11) My Final Form (What I Leave As)

I exit as `AgentResponse` (inside `TurnResult`, or inside streamed `response` events) with:

1. executive answer text,
2. confidence,
3. why-it-matters statement,
4. metrics,
5. evidence rows,
6. insight bullets,
7. suggested next questions,
8. assumptions list,
9. trace (`t1`, `t2`, `t3`),
10. `dataTables` (raw/explorable results),
11. `artifacts` (ranking/comparison/trend/distribution modules).

So I begin as one line of user text, and I leave as a governed, explainable analytics package.

## 12) Why This Feels More Complex Than A POC

A POC usually does:

1. one prompt,
2. one SQL,
3. one answer.

This backend keeps that core shape but adds enterprise controls:

1. route/plan decomposition,
2. governance guardrails,
3. validation gates,
4. deterministic fallback and repair,
5. streaming UX support,
6. provider-mode swap without orchestration rewrite.

That extra machinery is the cost of keeping behavior stable when models, providers, and data quality vary.

## 13) Operational Commands (Work-Machine Friendly)

From repo root:

```bash
npm ci
npm run setup:orchestrator
npm run dev:orchestrator
```

Sandbox service (second terminal):

```bash
npm run dev:sandbox-cortex
```

Backend tests:

```bash
npm --workspace @ci/orchestrator run test
```
