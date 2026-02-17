# Conversational Analytics Agent (Banking-Ready)

Production-oriented monorepo for a fast, explainable conversational analytics agent with:
- Next.js + Tailwind frontend (`apps/web`)
- FastAPI orchestrator backend (`apps/orchestrator`)
- Shared contracts (`packages/contracts`)
- Semantic model package (`packages/semantic-model`)
- Evaluation harness (`packages/eval-harness`)

This repo supports:
- Streamed responses
- Deterministic workflow + bounded agentic reasoning
- Mock mode locally, then switch to Azure OpenAI + Snowflake Cortex Analyst by env toggle
- In-UI tabular data explorer with CSV/JSON export

## Current Backend Status

- Mock mode is fully implemented for local UX/demo/testing.
- Real mode is wired for:
  - route classification
  - bounded planning
  - SQL generation + guardrails
  - Snowflake execution
  - validation and insight synthesis
- Semantic model source is currently JSON:
  - `/Users/joe/Code/ci_analyst/packages/semantic-model/models/banking-core.v1.json`

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

## Quick Start (Python Backend + Next.js Frontend)

Prerequisites:
- Node.js 20+
- Python 3.10+

1. Install workspace dependencies:
```bash
cd /Users/joe/Code/ci_analyst
npm ci
```

2. (Optional but recommended) Create and activate a Python virtual environment:
```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
# .\.venv\Scripts\Activate.ps1
```

If `python` is not available on Windows, use `py -3` in the same commands.

`npm run setup:orchestrator` and orchestrator npm scripts auto-detect Python (`python`, `py -3`, or `python3`).

3. Install Python backend dependencies:
```bash
npm run setup:orchestrator
```

4. Copy env templates:
```bash
cp /Users/joe/Code/ci_analyst/apps/orchestrator/.env.example /Users/joe/Code/ci_analyst/apps/orchestrator/.env
cp /Users/joe/Code/ci_analyst/apps/web/.env.example /Users/joe/Code/ci_analyst/apps/web/.env.local
```

5. Run orchestrator in mock mode (Python FastAPI):
```bash
npm run dev:orchestrator
```

Alternative direct command:
```bash
cd /Users/joe/Code/ci_analyst/apps/orchestrator
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

6. In another shell, run frontend in mock mode:
```bash
npm run dev:web
```

7. Open [http://localhost:3000](http://localhost:3000)

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
- optional orchestration controls (`REAL_FAST_PLAN_STEPS`, `REAL_DEEP_PLAN_STEPS`, `REAL_LLM_*`)
- `WEB_USE_LOCAL_MOCK=false`
- `ORCHESTRATOR_URL=http://localhost:8787`

3. Start orchestrator + frontend.

4. If your enterprise Snowflake wrapper expects a different endpoint/body format than `/query`, adjust:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/snowflake_cortex.py`

## Quality Commands

```bash
npm run lint
npm run test
npm run build
npm run eval
```

`npm run eval` expects orchestrator running on `http://localhost:8787` by default.

## Enterprise Registry Notes

- For long-term deterministic installs on enterprise mirrors, use `npm ci` (not `npm install`) on your work machine.
- The web lint config is intentionally minimal to avoid frequent mirror lag on fast-moving lint plugin packages.

## Security and Governance Notes

- UI displays **analysis trace summaries**, not raw private chain-of-thought.
- SQL and semantic behavior are designed around allowlists and versioned contracts.
- Keep PII controls in Snowflake and semantic model definitions.

## Key Docs

- `/Users/joe/Code/ci_analyst/docs/conversational-analytics-master-plan.md`
- `/Users/joe/Code/ci_analyst/docs/implementation-blueprint.md`
- `/Users/joe/Code/ci_analyst/docs/api-contracts.md`
- `/Users/joe/Code/ci_analyst/docs/prompts-and-policies.md`
- `/Users/joe/Code/ci_analyst/docs/evaluation-and-tests.md`
- `/Users/joe/Code/ci_analyst/docs/runbook-and-cutover.md`
- `/Users/joe/Code/ci_analyst/docs/frontend-ux-spec.md`
