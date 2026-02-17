# Conversational Analytics Agent (Banking-Ready Scaffold)

Production-oriented monorepo scaffold for a fast, explainable conversational analytics agent with:
- Next.js + Tailwind frontend (`apps/web`)
- FastAPI orchestrator backend (`apps/orchestrator`)
- Shared contracts (`packages/contracts`)
- Semantic model package (`packages/semantic-model`)
- Evaluation harness (`packages/eval-harness`)

This repo is pre-wired for:
- Streamed responses
- Deterministic workflow + bounded agentic reasoning
- Mock mode locally, then switch to Azure OpenAI + Snowflake Cortex Analyst by env toggle
- In-UI tabular data explorer with CSV/JSON export

## Monorepo Structure

```text
/Users/joe/Code/ci_analyst
  apps/
    web/
    orchestrator/
  packages/
    contracts/
    semantic-model/
    eval-harness/
  docs/
```

## Quick Start

1. Install workspace dependencies:
```bash
cd /Users/joe/Code/ci_analyst
npm install
```

2. Install Python backend dependencies:
```bash
npm run setup:orchestrator
```

3. Run orchestrator in mock mode:
```bash
npm run dev:orchestrator
```

4. In another shell, run frontend in mock mode:
```bash
npm run dev:web
```

5. Open [http://localhost:3000](http://localhost:3000)

## Streaming UX

The frontend uses `POST /api/chat/stream` and incrementally renders:
- status events (`intent`, `SQL`, `validation`)
- answer deltas (token streaming)
- final structured response payload

Protocol: `application/x-ndjson`

To slow mock streaming for demos, tune:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`: `MOCK_STREAM_STATUS_DELAY_MS`, `MOCK_STREAM_TOKEN_DELAY_MS`, `MOCK_STREAM_RESPONSE_DELAY_MS`
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`: `WEB_MOCK_STATUS_DELAY_MS`, `WEB_MOCK_TOKEN_DELAY_MS`, `WEB_MOCK_RESPONSE_DELAY_MS`

## Switching to Real Providers (Work Machine)

1. Copy env templates:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.example` -> `.env`
- `/Users/joe/Code/ci_analyst/apps/web/.env.example` -> `.env.local`

2. Set:
- `USE_MOCK_PROVIDERS=false`
- Azure variables (`AZURE_OPENAI_*`)
- Snowflake variables (`SNOWFLAKE_CORTEX_*`)
- optional semantic model override (`SEMANTIC_MODEL_PATH=/absolute/path/to/model.json`)
- `WEB_USE_LOCAL_MOCK=false`
- `ORCHESTRATOR_URL=http://localhost:8787`

3. Start orchestrator + frontend.

No code changes required for initial cutover.

## Quality Commands

```bash
npm run lint
npm run test
npm run build
npm run eval
```

`npm run eval` expects orchestrator running on `http://localhost:8787` by default.

## Security and Governance Notes

- UI displays **analysis trace summaries**, not raw private chain-of-thought.
- SQL and semantic behavior are designed around allowlists and versioned contracts.
- Keep PII controls in Snowflake and semantic model definitions.

## Key Docs

- `/Users/joe/Code/ci_analyst/docs/conversational-analytics-master-plan.md`
- `/Users/joe/Code/ci_analyst/docs/implementation-blueprint.md`
- `/Users/joe/Code/ci_analyst/docs/prompts-and-policies.md`
- `/Users/joe/Code/ci_analyst/docs/runbook-and-cutover.md`
- `/Users/joe/Code/ci_analyst/docs/frontend-ux-spec.md`
