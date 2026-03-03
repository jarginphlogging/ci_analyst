# CLAUDE.md — CI Analyst Codebase Guide

This file provides context for AI assistants working in this repository.

---

## What This Project Is

A production-oriented conversational analytics agent ("chat with data") built
for a banking environment. Users ask natural language questions; the agent
generates SQL, executes it, and returns streamed, structured, insight-rich
responses with charts or tables.

**Primary objectives:** minimal latency, maximum insight and data quality.

---

## Monorepo Structure

```
ci_analyst/
  apps/
    web/            — Next.js 16 + React 19 + Tailwind v3 frontend
    orchestrator/   — FastAPI Python backend (port 8787)
  packages/
    contracts/      — Zod-validated shared TypeScript types
    semantic-model/ — Banking semantic model definitions (JSON)
    eval-harness/   — Evaluation harness (Node.js ESM)
  scripts/
    run-python.mjs  — Cross-platform Python resolver (python/py -3/python3)
  docs/             — Architecture docs and specs
  AGENTS.md         — Product vision and engineering constraints
  README.md         — Setup and operational runbook
  PLAN.md           — Pipeline walkthrough with example prompts/outputs
```

---

## Core Architecture: The Pipeline

Every user query flows through four deterministic stages:

```
User query
    │
    ▼
1. Planner (LLM)       — classifies complexity, decomposes subtasks, decides
    │                    presentation intent (inline/table/chart)
    ▼
2. Executor (SQL)      — sends subtask questions to Cortex Analyst, gets SQL +
    │                    result sets back; deterministic validation runs on
    │                    every query (syntax → safety → schema → sanity)
    ▼
3. Data Summarizer     — deterministic Python: builds compact statistics summary
    │                    from result sets so the LLM never sees raw rows
    ▼
4. Synthesizer (LLM)   — writes narrative + produces chart_config / table_config
    │                    from the summary; raw data bypasses LLM entirely
    ▼
SSE stream to frontend (NDJSON, `application/x-ndjson`)
```

**Key principle:** LLM decides semantics; Python enforces contracts and
compresses data context. Never hardcode domain logic; keep orchestration
logic generalist.

---

## Provider Modes

The orchestrator supports three interchangeable modes set via `PROVIDER_MODE`:

| Mode      | LLM                     | SQL Provider              | Data Source      |
|-----------|-------------------------|---------------------------|------------------|
| `mock`    | Static mock responses   | Mock SQL results          | Hardcoded        |
| `sandbox` | Anthropic Claude API    | Local sandbox Cortex shim | SQLite (seeded)  |
| `prod`    | Azure OpenAI            | Snowflake Cortex Analyst  | Snowflake        |

Switch modes by editing env files only — no code changes required.

Provider swap points:
- `apps/orchestrator/app/providers/azure_openai.py`
- `apps/orchestrator/app/providers/anthropic_llm.py`
- `apps/orchestrator/app/providers/snowflake_cortex.py`
- `apps/orchestrator/app/providers/sandbox_cortex.py`
- `apps/orchestrator/app/providers/factory.py` — mode registry

---

## Key Source Files

### Backend (Python / FastAPI)

| File | Purpose |
|------|---------|
| `apps/orchestrator/app/main.py` | FastAPI app, `/health`, `/v1/chat/turn`, `/v1/chat/stream` endpoints |
| `apps/orchestrator/app/config.py` | `Settings` dataclass — all config loaded from env via `python-dotenv` |
| `apps/orchestrator/app/models.py` | Pydantic models: `ChatTurnRequest`, `AgentResponse`, `TraceStep`, SSE event types |
| `apps/orchestrator/app/services/orchestrator.py` | `ConversationalOrchestrator` — wires all pipeline stages, manages session history (last 12 turns, 8 used as context) |
| `apps/orchestrator/app/services/stages/planner_stage.py` | Planner LLM call: complexity tier, turn type, subtask decomposition, presentation intent |
| `apps/orchestrator/app/services/stages/sql_stage.py` | SQL execution stage with retry loop (`SQL_MAX_ATTEMPTS`, default 3) |
| `apps/orchestrator/app/services/stages/sql_stage_generation.py` | SQL generation logic |
| `apps/orchestrator/app/services/stages/data_summarizer_stage.py` | Deterministic pre-computation of data stats for LLM context |
| `apps/orchestrator/app/services/stages/synthesis_stage.py` | Synthesizer LLM call + incremental answer deltas |
| `apps/orchestrator/app/services/stages/validation_stage.py` | SQL validation: syntax, safety blocklist, schema check, sanity limit |
| `apps/orchestrator/app/services/llm_json.py` | Robust JSON extraction from LLM responses |
| `apps/orchestrator/app/services/llm_schemas.py` | Pydantic schemas for LLM-structured outputs |
| `apps/orchestrator/app/services/semantic_model.py` | Semantic model loading and summary generation |
| `apps/orchestrator/app/services/sql_guardrails.py` | SQL safety guardrails |
| `apps/orchestrator/app/services/table_analysis.py` | Table analysis and artifact generation |
| `apps/orchestrator/app/providers/protocols.py` | `LLMProvider` and `SQLProvider` protocol interfaces |
| `apps/orchestrator/app/providers/factory.py` | Provider factory — resolves providers from `PROVIDER_MODE` |
| `apps/orchestrator/app/observability.py` | Structured JSON logging with request/session context binding |
| `apps/orchestrator/app/sandbox/sandbox_sca_service.py` | Local Cortex Analyst-compatible service (port 8788) |
| `apps/orchestrator/app/sandbox/sqlite_store.py` | SQLite-backed data store for sandbox mode |
| `apps/orchestrator/app/prompts/templates.py` | LLM prompt templates |

### Frontend (Next.js / TypeScript)

| File | Purpose |
|------|---------|
| `apps/web/src/app/page.tsx` | Root page |
| `apps/web/src/app/layout.tsx` | Root layout |
| `apps/web/src/app/api/chat/` | Next.js API route: proxies to orchestrator or runs web mock |
| `apps/web/src/app/api/system-status/` | System status API route |
| `apps/web/src/lib/types.ts` | All TypeScript types: `ChatMessage`, `AgentResponse`, `ChatStreamEvent`, `ChartConfig`, `TableConfig`, etc. |
| `apps/web/src/lib/stream.ts` | SSE stream consumer — parses NDJSON events, builds `AgentResponse` |
| `apps/web/src/lib/mock-stream.ts` | Web-side mock stream for `WEB_BACKEND_MODE=web_mock` |
| `apps/web/src/lib/mock-agent.ts` | Mock agent response data |
| `apps/web/src/lib/server-env.ts` | Server-side env config |
| `apps/web/src/components/agent-workspace.tsx` | Main chat workspace component |
| `apps/web/src/components/analysis-trace.tsx` | Renders the agent trace panel |
| `apps/web/src/components/data-explorer.tsx` | Tabular data explorer with CSV/JSON export |
| `apps/web/src/components/evidence-table.tsx` | Evidence table component |

### Packages

| Package | Purpose |
|---------|---------|
| `packages/contracts/` | Zod schemas for shared API contracts |
| `packages/semantic-model/` | Banking semantic model JSON + TypeScript wrappers |
| `packages/eval-harness/` | Evaluation runner: token hit rate, numeric assertions, route classification, p50/p95 latency thresholds |

---

## Environment Configuration

### Backend: `apps/orchestrator/.env`

```bash
PROVIDER_MODE=mock                  # mock | sandbox | prod

# Anthropic (sandbox mode)
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-sonnet-latest

# Azure OpenAI (prod mode)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_AUTH_MODE=api_key      # api_key | certificate
AZURE_TENANT_ID=
AZURE_SPN_CLIENT_ID=
AZURE_SPN_CERT_PATH=

# Snowflake (prod mode)
SNOWFLAKE_CORTEX_BASE_URL=
SNOWFLAKE_CORTEX_API_KEY=
SNOWFLAKE_CORTEX_WAREHOUSE=
SNOWFLAKE_CORTEX_DATABASE=
SNOWFLAKE_CORTEX_SCHEMA=

# Orchestration tuning
SQL_MAX_ATTEMPTS=3
REAL_FAST_PLAN_STEPS=2
REAL_DEEP_PLAN_STEPS=4
REAL_LLM_TEMPERATURE=0.1
REAL_LLM_MAX_TOKENS=1400

# Mock stream delays (demo tuning)
MOCK_STREAM_STATUS_DELAY_MS=700
MOCK_STREAM_TOKEN_DELAY_MS=120
MOCK_STREAM_RESPONSE_DELAY_MS=450
```

### Frontend: `apps/web/.env.local`

```bash
WEB_BACKEND_MODE=web_mock           # web_mock | orchestrator
ORCHESTRATOR_URL=http://localhost:8787

# Web mock stream delays
WEB_MOCK_STATUS_DELAY_MS=
WEB_MOCK_TOKEN_DELAY_MS=
WEB_MOCK_RESPONSE_DELAY_MS=
```

Reference templates exist at `.env.mock`, `.env.sandbox`, `.env.prod` and
`.env.web-mock`, `.env.orchestrator` for each workspace.

---

## Development Commands

All commands run from repo root:

```bash
npm ci                        # Install all JS/TS dependencies (canonical — do not use npm install)
npm run setup:orchestrator    # Install Python deps via pip into orchestrator workspace
npm run dev:web               # Start Next.js frontend (port 3000)
npm run dev:orchestrator      # Start FastAPI backend (port 8787, hot reload)
npm run dev:sandbox-cortex    # Start sandbox Cortex shim (port 8788, hot reload)
npm run lint                  # Lint all workspaces
npm run test                  # Test all workspaces
npm run build                 # Build all workspaces
npm run eval                  # Run evaluation harness (requires orchestrator on :8787)
```

Python can be run directly:
```bash
cd apps/orchestrator
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
python -m pytest -q
```

Health check endpoints:
```bash
curl http://127.0.0.1:8787/health   # orchestrator
curl http://127.0.0.1:8788/health   # sandbox Cortex
```

---

## API Endpoints

### POST `/v1/chat/turn` (non-streaming)
Request: `ChatTurnRequest` — `{ message, sessionId?, history? }`
Response: `TurnResult` with full `AgentResponse`

### POST `/v1/chat/stream` (streaming)
Request: same as above
Response: `application/x-ndjson` stream of `ChatStreamEvent` objects

SSE event sequence:
1. `{ type: "status", message: "..." }` — progress updates
2. `{ type: "answer_delta", delta: "..." }` — streamed narrative tokens
3. `{ type: "response", response: AgentResponse, phase: "draft"|"final" }` — structured payload
4. `{ type: "done" }` — stream complete
5. `{ type: "error", message: "..." }` — on failure

---

## Data Flow: SQL Validation

Every generated SQL query passes four deterministic stages before execution:

1. **Syntax** — parsed with `sqlglot` (Snowflake dialect)
2. **Safety** — blocklist check: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `GRANT`, `REVOKE`, `COPY`, `PUT`
3. **Schema** — all referenced tables and columns validated against the semantic model
4. **Sanity** — row limit enforced if no aggregation or LIMIT clause (`SELECT * FROM (...) LIMIT 10000`)

---

## TypeScript Types (Frontend)

Core types live in `apps/web/src/lib/types.ts`:

- `ChatMessage` — user or assistant message with optional `AgentResponse`
- `AgentResponse` — full structured response: `answer`, `confidence`, `metrics`, `evidence`, `insights`, `trace`, `chartConfig`, `tableConfig`, `dataTables`, `artifacts`, `suggestedQuestions`
- `TraceStep` — one pipeline stage entry with status, timing, SQL, quality checks
- `ChartConfig` — `{ type, x, y, series, xLabel, yLabel, yFormat }`
- `TableConfig` — `{ style, columns, sortBy, sortDir, showRank }`
- `ChatStreamEvent` — discriminated union of all SSE event types

---

## Code Conventions

### General
- **Never hardcode** domain logic, queries, or thresholds — all config via env
- Keep orchestration logic generalist; avoid overfitting to specific query patterns
- **LLM decides semantics; Python enforces contracts and compresses data context**
- Decision-making belongs in the LLM; complex branching Python logic is a red flag
- Prefer solutions that are stable long-term in enterprise Windows environments

### Python (Backend)
- All new modules must use `from __future__ import annotations`
- Configuration goes in `app/config.py` `Settings` dataclass, loaded from env
- LLM calls use the provider protocol in `app/providers/protocols.py` — never call LLM APIs directly from stage code
- Structured JSON logging via `app/observability.py` — use `logger.info(..., extra={...})` with event keys
- Pydantic v2 for all request/response models
- `pytest` + `pytest-asyncio` for tests; test files in `apps/orchestrator/tests/`
- Cross-platform Python: scripts use `scripts/run-python.mjs` which tries `python`, `py -3`, `python3`

### TypeScript / React (Frontend)
- `npm ci` only — never `npm install` ad-hoc
- Tailwind v3 + standard PostCSS (no `lightningcss` — avoids Windows binary issues)
- React 19 + Next.js 16
- Types from `apps/web/src/lib/types.ts` and `@ci/contracts`
- Frontend is production-grade — avoid generic "AI slop" aesthetics; use distinctive, purposeful design

### Contracts
- Shared types validated with Zod in `packages/contracts/`
- Type changes require updating both Python Pydantic models and TypeScript/Zod schemas

---

## Presentation Intent System

The Planner LLM classifies each query's expected output using a decision tree:

| Signal | Display Type | Chart/Table Style |
|--------|-------------|-------------------|
| Single scalar value | `inline` | — |
| Time dimension, one measure | `chart` | `line` |
| Time dimension, multiple categories | `chart` | `line` |
| Period-over-period deltas | `chart` | `grouped_bar` |
| Composition, < 8 categories | `chart` | `bar` or `stacked_bar` |
| Composition, 8+ categories | `table` | `simple` |
| Ranking / top-N | `table` | `ranked` |
| Entity comparison | `table` | `comparison` |
| Filtered list | `table` | `simple` |

The Synthesizer may override the Planner's intent (e.g., too many series → downgrade chart to table).
Chart column mapping is validated deterministically post-LLM.

---

## Session Management

- Session history stored in-memory per `sessionId` on the orchestrator
- Last 12 turns stored; last 8 used as conversation context
- Turn types: `new` | `refine` | `followup` — classified by the Planner

---

## Testing

```bash
# Backend Python tests
npm run test --workspace @ci/orchestrator
# or directly:
cd apps/orchestrator && python -m pytest -q

# Frontend tests (Vitest)
npm run test --workspace @ci/web

# Evaluation harness (requires running orchestrator)
npm run eval
```

Test files:
- `apps/orchestrator/tests/` — orchestrator, planner, SQL stages, providers, sandbox, guardrails
- `apps/web/src/lib/stream.test.ts` — SSE stream parsing

Eval harness (`packages/eval-harness/`) evaluates:
- Token hit rate against expected answer tokens
- Numeric assertions
- Expected route classification
- Route-specific latency thresholds (p50/p95)

---

## Delivery Checklist

Before merging changes that affect setup or build tooling, validate:

```bash
npm ci
npm run setup:orchestrator
npm run dev:orchestrator    # should start without errors
npm run dev:web             # should start without errors
npm run lint
npm run test
npm run build
```

---

## Work Machine Notes (Windows Enterprise)

- Target: Windows corporate environment with internal package mirrors
- No secrets or code pushed from the work machine
- Use `npm ci` (not `npm install`) for deterministic installs
- Avoid native binary dependencies in frontend build (reason: Tailwind v3, no `lightningcss`)
- Python scripts use the cross-platform resolver at `scripts/run-python.mjs`
- To pull upstream changes on work machine: `git stash push -u -m "work-local"` → pull → `git stash pop`

---

## Security Notes

- UI displays **analysis trace summaries**, not raw LLM chain-of-thought
- SQL validation blocklist prevents any write/DDL operations
- PII controls live in Snowflake and the semantic model — not in orchestration code
- SQL and semantic behavior use allowlists and versioned contracts
- Secrets in `.env` files only — never committed

---

## Key Documentation

- `AGENTS.md` — product vision, engineering constraints, delivery rules
- `README.md` — full setup instructions for all modes
- `PLAN.md` — end-to-end pipeline walkthrough with example LLM prompts and outputs
- `docs/conversational-analytics-master-plan.md`
- `docs/implementation-blueprint.md`
- `docs/backend-deep-dive.md`
- `docs/api-contracts.md`
- `docs/prompts-and-policies.md`
- `docs/evaluation-and-tests.md`
- `docs/frontend-ux-spec.md`
- `docs/runbook-and-cutover.md`
