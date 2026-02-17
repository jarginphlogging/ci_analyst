# Runbook and Cutover

## 1) Local Mock Workflow

1. `npm install`
2. `npm run setup:orchestrator`
3. `npm run dev:orchestrator`
4. `npm run dev:web`
5. Confirm:
   - frontend streams answer tokens
   - trace panel expands
   - evidence table sorts
   - retrieved data tables can be exported as CSV/JSON

## 2) Work Machine Cutover

## Backend
- File: `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`
- Required:
  - `USE_MOCK_PROVIDERS=false`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_DEPLOYMENT`
  - `SNOWFLAKE_CORTEX_BASE_URL`
  - `SNOWFLAKE_CORTEX_API_KEY`
  - optional `SEMANTIC_MODEL_PATH` (absolute path to model JSON)
  - optional `REAL_FAST_PLAN_STEPS`, `REAL_DEEP_PLAN_STEPS` for bounded workflow control

## Frontend
- File: `/Users/joe/Code/ci_analyst/apps/web/.env.local`
- Required:
  - `WEB_USE_LOCAL_MOCK=false`
  - `ORCHESTRATOR_URL=http://localhost:8787`

## 3) Health Checks

- `GET /health` should return status `ok`
- `POST /v1/chat/turn` should return structured payload
- `POST /v1/chat/stream` should return NDJSON with `status`, `answer_delta`, `response`, `done`

## 4) Troubleshooting

- If stream stalls:
  - check reverse proxy buffering settings
  - verify `Content-Type` is `application/x-ndjson`
- If provider calls fail:
  - verify endpoint URL and API version
  - verify credentials and role permissions
- If frontend cannot reach backend:
  - verify `ORCHESTRATOR_URL`
  - verify CORS/network policy in enterprise environment
