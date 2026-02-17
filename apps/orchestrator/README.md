# @ci/orchestrator (Python)

FastAPI orchestration service for conversational analytics.

## Endpoints

- `GET /health`
- `POST /v1/chat/turn`
- `POST /v1/chat/stream` (`application/x-ndjson`)

## Pipeline Shape

1. classify route (`fast_path` or `deep_path`)
2. generate bounded plan
3. execute governed SQL steps
4. run numeric validation checks
5. build answer + evidence + insights + trace + retrievable tables
6. carry forward bounded prior-turn context into route/plan/sql/response prompts

Provider modes:
- `mock`: static deterministic demo responses
- `sandbox`: Anthropic LLM + local Cortex-compatible REST + local SQLite data
- `prod`: Azure OpenAI + Snowflake Cortex Analyst

`prod` mode uses:
- Azure OpenAI for routing, planning, SQL generation, and narrative synthesis
- Snowflake Cortex SQL execution adapter
- deterministic SQL guardrails and validation checks
- optional bounded parallel SQL execution (disabled by default)

`sandbox` mode uses:
- Anthropic Messages API for routing/planning/sql/synthesis
- Local Cortex-compatible `/query` REST service
- Local seeded SQLite dataset with allowlisted banking tables

Azure auth supports:
- `AZURE_OPENAI_AUTH_MODE=api_key` with `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_AUTH_MODE=certificate` with `AZURE_TENANT_ID`, `AZURE_SPN_CLIENT_ID`, `AZURE_SPN_CERT_PATH` (optional `AZURE_SPN_CERT_PASSWORD`)
- optional enterprise gateway header via `AZURE_OPENAI_GATEWAY_API_KEY` and `AZURE_OPENAI_GATEWAY_API_KEY_HEADER`

## Local Setup

```bash
cd /Users/joe/Code/ci_analyst/apps/orchestrator
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
# .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.mock.example .env
```

Environment templates:
- `.env.mock.example`
- `.env.sandbox.example`
- `.env.prod.example`

Runtime file:
- `.env` (auto-loaded by orchestrator startup)

## Run

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:orchestrator
```

The npm scripts auto-detect Python (`python`, `py -3`, or `python3`).

For `sandbox` mode, run local Cortex shim in a second terminal:

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:sandbox-cortex
```

Direct command:
```bash
cd /Users/joe/Code/ci_analyst/apps/orchestrator
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

## Test

```bash
cd /Users/joe/Code/ci_analyst
npm --workspace @ci/orchestrator run test
```

## Where to Integrate Real Connectors

- `app/providers/azure_openai.py`
- `app/providers/snowflake_cortex.py`
- `app/providers/anthropic_llm.py`
- `app/providers/sandbox_cortex.py`
- `app/providers/factory.py`
- `app/providers/protocols.py`
- `app/services/dependencies.py`
- `app/sandbox/cortex_service.py`
- `app/sandbox/sqlite_store.py`
- stage modules:
  - `app/services/stages/planner_stage.py`
  - `app/services/stages/sql_stage.py`
  - `app/services/stages/validation_stage.py`
  - `app/services/stages/synthesis_stage.py`
- prompt templates: `app/prompts/templates.py`
- SQL policy checks: `app/services/sql_guardrails.py`
- semantic model loader: `app/services/semantic_model.py`

## Mock Streaming Controls

Set these in `.env` to slow down and visualize the live run:

- `MOCK_STREAM_STATUS_DELAY_MS` (default `700`)
- `MOCK_STREAM_TOKEN_DELAY_MS` (default `120`)
- `MOCK_STREAM_RESPONSE_DELAY_MS` (default `450`)

## Real SQL Parallelism (Optional)

Enable bounded parallel SQL execution only when your warehouse and governance controls support it:

- `REAL_ENABLE_PARALLEL_SQL=false` (default)
- `REAL_MAX_PARALLEL_QUERIES=3`

Behavior:
- SQL planning/generation remains deterministic and sequential.
- Query execution can run in parallel with bounded concurrency.
- Final result ordering remains deterministic by plan step index.

## Mode Selection

Set in `.env`:

- `PROVIDER_MODE=mock` (default)
- `PROVIDER_MODE=sandbox` (local end-to-end testing without enterprise services)
- `PROVIDER_MODE=prod` (Azure/Snowflake/Cortex)

Backward-compat note:
- if `PROVIDER_MODE` is omitted, `USE_MOCK_PROVIDERS=true` maps to `mock`, `false` maps to `prod`.
