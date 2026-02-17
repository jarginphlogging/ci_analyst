# Runbook and Cutover

## 1) Local Mock Workflow

1. `npm install`
2. `npm run setup:orchestrator`
3. Edit `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`: `PROVIDER_MODE=mock`
4. Edit `/Users/joe/Code/ci_analyst/apps/web/.env.local`: `WEB_BACKEND_MODE=web_mock`
5. `npm run dev:orchestrator`
6. `npm run dev:web`
7. Confirm:
   - frontend streams answer tokens
   - trace panel expands
   - evidence table sorts
   - retrieved data tables can be exported as CSV/JSON

## 2) Local Sandbox Workflow (Realistic pre-prod test)

1. Set `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`:
   - `PROVIDER_MODE=sandbox`
   - `ANTHROPIC_API_KEY=<key>`
   - `SANDBOX_CORTEX_API_KEY=` (blank unless you want local auth)
2. Set `/Users/joe/Code/ci_analyst/apps/web/.env.local`:
   - `WEB_BACKEND_MODE=orchestrator`
   - `ORCHESTRATOR_URL=http://localhost:8787`
3. Start local Cortex shim:
   - `npm run dev:sandbox-cortex`
4. Start orchestrator:
   - `npm run dev:orchestrator`
5. Start web:
   - `npm run dev:web`

## 3) Work Machine Cutover

## Backend
- File: `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`
- Required:
  - `PROVIDER_MODE=prod`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_DEPLOYMENT`
  - `SNOWFLAKE_CORTEX_BASE_URL`
  - `SNOWFLAKE_CORTEX_API_KEY`
  - (These Snowflake vars are not required in sandbox mode.)
- optional `SEMANTIC_MODEL_PATH` (absolute path to model JSON)
  - optional `REAL_FAST_PLAN_STEPS`, `REAL_DEEP_PLAN_STEPS` for bounded workflow control

## Frontend
- File: `/Users/joe/Code/ci_analyst/apps/web/.env.local`
- Required:
  - `WEB_BACKEND_MODE=orchestrator`
  - `ORCHESTRATOR_URL=http://localhost:8787`

## 4) Health Checks

- `GET /health` should return status `ok`
- `POST /v1/chat/turn` should return structured payload
- `POST /v1/chat/stream` should return NDJSON with `status`, `answer_delta`, `response`, `done`

## 5) Troubleshooting

- If stream stalls:
  - check reverse proxy buffering settings
  - verify `Content-Type` is `application/x-ndjson`
- If provider calls fail:
  - verify endpoint URL and API version
  - verify credentials and role permissions
- If frontend cannot reach backend:
  - verify `ORCHESTRATOR_URL`
  - verify CORS/network policy in enterprise environment
