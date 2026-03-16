# @ci/orchestrator (Python)

FastAPI orchestration service for conversational analytics.

## Endpoints

- `GET /health`
- `POST /v1/chat/turn`
- `POST /v1/chat/stream` (`application/x-ndjson`)

## Pipeline Shape

1. generate bounded plan
2. execute governed SQL steps
3. build deterministic pandas-based table summaries (no LLM) for synthesis context
4. run numeric validation checks
5. synthesize final insights from original query + plan + executed SQL + table summaries
6. carry forward bounded prior-turn context into plan/sql/response prompts

Provider modes:
- `sandbox`: Anthropic LLM + local Cortex-compatible REST + local SQLite data
- `prod-sandbox`: Azure OpenAI LLM + local Cortex-compatible REST + local SQLite data
- `prod`: Azure OpenAI + Snowflake Cortex Analyst + Snowflake Python Connector

`prod` mode uses:
- Azure OpenAI for routing, planning, and narrative synthesis
- Snowflake Cortex Analyst REST API for SQL generation and clarification turns
- Snowflake Python Connector for SQL execution
- deterministic SQL guardrails and validation checks
- bounded parallel execution for independent steps, with serial fallback for dependent steps

`sandbox` mode uses:
- Anthropic Messages API for routing/planning/sql/synthesis
- Local pseudo-Cortex Analyst REST service with:
  - `message` endpoint (NL question -> SQL-generation payload + light response metadata)
  - clarification handling for vague questions
  - conversation memory by `conversationId`
  - raw `/query` endpoint for direct SQL execution
- Local seeded SQLite dataset with allowlisted banking tables
- No external Snowflake/Cortex API key required for sandbox mode.

`prod-sandbox` mode uses:
- `LLM_PROVIDER=azure_openai` or `LLM_PROVIDER=anthropic_bedrock`
- The selected LLM provider for routing, planning, and narrative synthesis
- Local pseudo-Cortex Analyst REST service for analyst-style SQL generation, powered by the same selected LLM provider
- Local seeded SQLite dataset with allowlisted banking tables
- No Snowflake connectivity required

Azure auth supports:
- `AZURE_OPENAI_AUTH_MODE=api_key` with `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_AUTH_MODE=certificate` with `AZURE_TENANT_ID`, `AZURE_SPN_CLIENT_ID`, `AZURE_SPN_CERT_PATH` (optional `AZURE_SPN_CERT_PASSWORD`)
- `AZURE_OPENAI_DEPLOYMENT` or `AZURE_OPENAI_MODEL` for the Azure deployment/model name
- optional enterprise gateway header via `AZURE_OPENAI_GATEWAY_API_KEY` (alias: `AZURE_API_KEY`) and `AZURE_OPENAI_GATEWAY_API_KEY_HEADER`

Anthropic Bedrock supports:
- `ANTHROPIC_BEDROCK_AWS_ACCOUNT_NUMBER`
- `ANTHROPIC_BEDROCK_AWS_REGION`
- `ANTHROPIC_BEDROCK_WORKSPACE_ID`
- `ANTHROPIC_BEDROCK_IS_EXECUTION_ROLE`
- `ANTHROPIC_BEDROCK_MODEL_ID`
- optional `ANTHROPIC_BEDROCK_MODEL_NAME`
- optional `ANTHROPIC_BEDROCK_ANTHROPIC_VERSION`
- enterprise runtime access to `cdao` plus AWS credentials available to the internal package path

Snowflake prod auth/config supports:
- Analyst generation: `SNOWFLAKE_CORTEX_BASE_URL`, `SNOWFLAKE_CORTEX_API_KEY`, and one semantic model reference (`SNOWFLAKE_CORTEX_SEMANTIC_MODEL_FILE` or `SNOWFLAKE_CORTEX_SEMANTIC_MODEL` or `SNOWFLAKE_CORTEX_SEMANTIC_VIEW` or `SNOWFLAKE_CORTEX_SEMANTIC_MODELS_JSON`)
- SQL execution: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, and one auth option (`SNOWFLAKE_PASSWORD` or `SNOWFLAKE_PRIVATE_KEY_FILE`)
- Optional execution context: `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_AUTHENTICATOR`

## Local Setup

```bash
cd /Users/joe/Code/ci_analyst
npm run setup:orchestrator
```

`pyproject.toml` pins `cryptography` and `pyOpenSSL` explicitly because some enterprise Windows mirrors
otherwise backtrack onto a source-only `cryptography` release, which triggers an avoidable Rust/bootstrap path.
It also pins `openai` because the orchestrator uses the official Azure OpenAI client for enterprise auth flows,
and `PyYAML` because semantic metadata now loads from `semantic_model.yaml` at runtime.

Runtime env:
- `.env` (single backend runtime file, auto-loaded by orchestrator startup)

## Run

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:orchestrator
```

The npm scripts auto-detect Python (`python`, `py -3`, or `python3`).

For `sandbox` and `prod-sandbox` modes, run the local Cortex shim in a second terminal:

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:sandbox-cortex
```

Direct command:
```bash
cd /Users/joe/Code/ci_analyst/apps/orchestrator
node ../../scripts/run-python.mjs -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

## Test

```bash
cd /Users/joe/Code/ci_analyst
npm --workspace @ci/orchestrator run test
```

## Where to Integrate Real Connectors

- `app/providers/azure_openai.py`
- `app/providers/snowflake_analyst.py`
- `app/providers/snowflake_connector_sql.py`
- `app/providers/anthropic_llm.py`
- `app/providers/sandbox_cortex.py`
- `app/providers/factory.py`
- `app/providers/protocols.py`
- `app/services/dependencies.py`
- `app/sandbox/sandbox_sca_service.py`
- `app/sandbox/sqlite_store.py`
- stage modules:
  - `app/services/stages/planner_stage.py`
  - `app/services/stages/sql_stage.py`
  - `app/services/stages/data_summarizer_stage.py`
  - `app/services/stages/validation_stage.py`
  - `app/services/stages/synthesis_stage.py`
- prompt templates: `app/prompts/templates.py`
- SQL policy checks: `app/services/sql_guardrails.py`
- semantic model source + loader path: `semantic_model.yaml`, `app/services/semantic_model_yaml.py`, `app/services/semantic_model.py`
- semantic guardrails loader: `app/services/semantic_policy.py`

## SQL Execution Concurrency

Execution behavior:
- Independent step levels execute in parallel in `sandbox`, `prod-sandbox`, and `prod`.
- Dependent step levels execute serially.
- Final result ordering remains deterministic by plan step index.

Concurrency controls:
- `REAL_MAX_PARALLEL_QUERIES=3`
- `SQL_MAX_ATTEMPTS=3` (max SQL rewrite/execute attempts before surfacing clarification)
- `PLAN_MAX_STEPS=5` (max planned SQL steps per turn)

SQL retry/tracing contract:
- SQL execution uses a centralized state machine (`app/services/stages/sql_state_machine.py`).
- Retry feedback events include normalized `phase`, `errorCode`, `errorCategory`, `attempt`, and optional `failedSql`.
- SQL regeneration retries are driven only by SQL execution failures (`phase=sql_execution`).
- SQL generation/provider failures do not enter the execution retry loop.
- `warehouseErrors` is an execution-only derived view.

## Mode Selection

Set in `.env`:

- `PROVIDER_MODE=sandbox` (local end-to-end testing without enterprise services)
- `PROVIDER_MODE=prod-sandbox` (`LLM_PROVIDER` + local Cortex emulator + SQLite)
- `PROVIDER_MODE=prod` (`LLM_PROVIDER` + Snowflake/Cortex)
- `LLM_PROVIDER=anthropic_direct` for `sandbox`
- `LLM_PROVIDER=azure_openai` or `LLM_PROVIDER=anthropic_bedrock` for `prod` and `prod-sandbox`
