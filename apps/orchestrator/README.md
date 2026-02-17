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

## Local Setup

```bash
cd /Users/joe/Code/ci_analyst/apps/orchestrator
python3 -m pip install -r requirements.txt
```

## Run

```bash
cd /Users/joe/Code/ci_analyst
npm run dev:orchestrator
```

## Test

```bash
cd /Users/joe/Code/ci_analyst
npm --workspace @ci/orchestrator run test
```

## Where to Integrate Real Connectors

- `app/providers/azure_openai.py`
- `app/providers/snowflake_cortex.py`
- `app/services/dependencies.py`
- prompt templates: `app/prompts/templates.py`
- SQL policy checks: `app/services/sql_guardrails.py`
- semantic model loader: `app/services/semantic_model.py`

## Mock Streaming Controls

Set these in `.env` to slow down and visualize the live run:

- `MOCK_STREAM_STATUS_DELAY_MS` (default `700`)
- `MOCK_STREAM_TOKEN_DELAY_MS` (default `120`)
- `MOCK_STREAM_RESPONSE_DELAY_MS` (default `450`)
