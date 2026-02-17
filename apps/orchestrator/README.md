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

Real mode (`USE_MOCK_PROVIDERS=false`) uses:
- Azure OpenAI for routing, planning, SQL generation, and narrative synthesis
- Snowflake Cortex SQL execution adapter
- deterministic SQL guardrails and validation checks

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
cp .env.example .env
```

## Run

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:orchestrator
```

The npm scripts auto-detect Python (`python`, `py -3`, or `python3`).

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
- `app/providers/factory.py`
- `app/providers/protocols.py`
- `app/services/dependencies.py`
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
