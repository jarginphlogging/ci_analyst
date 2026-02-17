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
- Three interchangeable provider modes (`mock`, `sandbox`, `prod`) switched by env only
- In-UI tabular data explorer with CSV/JSON export

## Current Backend Status

- Mock mode is fully implemented for local UX/demo/testing.
- Sandbox mode is implemented for realistic local e2e testing:
  - Anthropic API as LLM
  - local Cortex-compatible REST shim
  - seeded local SQLite analytics tables
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

This runs in the orchestrator workspace to ensure installs and runtime use the same Python interpreter.

4. Edit runtime env files (already present in repo):
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`

For quick local mock startup, set:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`: `PROVIDER_MODE=mock`
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`: `WEB_BACKEND_MODE=web_mock`

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

## Environment Files (Single Source of Truth)

Backend env file:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`

Frontend env file:
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`

Optional reference templates:
- Mock:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.mock.example`
  - `/Users/joe/Code/ci_analyst/apps/web/.env.web-mock.example`
- Sandbox:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.sandbox.example`
  - `/Users/joe/Code/ci_analyst/apps/web/.env.orchestrator.example`
- Prod:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.prod.example`
  - `/Users/joe/Code/ci_analyst/apps/web/.env.orchestrator.example`

Note:
- Orchestrator now auto-loads `/Users/joe/Code/ci_analyst/apps/orchestrator/.env` on startup.
- Root `/Users/joe/Code/ci_analyst/.env` is not used for normal runtime.

## Sandbox Mode (Anthropic + Local Cortex + SQLite)

1. Edit `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`:
- `PROVIDER_MODE=sandbox`
- `ANTHROPIC_API_KEY=<your-key>`
- optional `ANTHROPIC_MODEL`

2. Edit `/Users/joe/Code/ci_analyst/apps/web/.env.local`:
- `WEB_BACKEND_MODE=orchestrator`
- `ORCHESTRATOR_URL=http://localhost:8787`

3. Install backend Python deps (once per environment):
```bash
cd /Users/joe/Code/ci_analyst
npm run setup:orchestrator
```

4. Start local Cortex-compatible sandbox service (Terminal 1):
```bash
cd /Users/joe/Code/ci_analyst
npm run dev:sandbox-cortex
```

5. Start orchestrator API (Terminal 2):
```bash
cd /Users/joe/Code/ci_analyst
npm run dev:orchestrator
```

6. Start frontend (Terminal 3):
```bash
cd /Users/joe/Code/ci_analyst
npm run dev:web
```

7. Open [http://localhost:3000](http://localhost:3000)

8. Optional health checks:
```bash
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8787/health
```

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

1. Edit runtime files directly:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`

2. Set:
- `PROVIDER_MODE=prod`
- Azure variables (`AZURE_OPENAI_*`)
  - auth mode: `AZURE_OPENAI_AUTH_MODE=api_key` or `AZURE_OPENAI_AUTH_MODE=certificate`
  - `api_key` mode: set `AZURE_OPENAI_API_KEY`
  - `certificate` mode: set `AZURE_TENANT_ID`, `AZURE_SPN_CLIENT_ID`, `AZURE_SPN_CERT_PATH` (and optional `AZURE_SPN_CERT_PASSWORD`)
  - optional gateway header support: `AZURE_OPENAI_GATEWAY_API_KEY`, `AZURE_OPENAI_GATEWAY_API_KEY_HEADER`
- Snowflake variables (`SNOWFLAKE_CORTEX_*`)
- optional semantic model override (`SEMANTIC_MODEL_PATH=/absolute/path/to/model.json`)
- optional orchestration controls (`REAL_FAST_PLAN_STEPS`, `REAL_DEEP_PLAN_STEPS`, `REAL_LLM_*`)
- `WEB_BACKEND_MODE=orchestrator`
- `ORCHESTRATOR_URL=http://localhost:8787`

3. Start orchestrator + frontend.

4. If your enterprise Snowflake wrapper expects a different endpoint/body format than `/query`, adjust:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/snowflake_cortex.py`

Provider swap points (no orchestration rewrite needed):
- LLM providers:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/azure_openai.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/anthropic_llm.py`
- SQL providers:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/snowflake_cortex.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/sandbox_cortex.py`
- Mode registry:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/factory.py`

## Work Machine Version Control Workflow

Use this workflow when you have local work-machine-only changes (for provider wiring/secrets integration) and need to pull upstream repo updates.

1. Stash local changes (tracked + untracked):
```bash
git stash push -u -m "work-local"
```

2. Pull latest repo changes:
```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

3. Re-apply local changes:
```bash
git stash pop
```

4. If conflicts occur:
```bash
git status
# resolve conflicted files
git add <resolved-file>
```

Notes:
- This workflow does not require commits or pushes from the work machine.
- Keep secrets in `.env` files only.
- Use this sequence each time before updating from `origin/main`.

## Quality Commands

```bash
npm run lint
npm run test
npm run build
npm run eval
```

`npm run eval` expects orchestrator running on `http://localhost:8787` by default.
It evaluates token hits, numeric assertions, expected route, and route-specific latency thresholds (p50/p95).

## Enterprise Registry Notes

- For long-term deterministic installs on enterprise mirrors, use `npm ci` (not `npm install`) on your work machine.
- The web lint config is intentionally minimal to avoid frequent mirror lag on fast-moving lint plugin packages.
- The web app uses Tailwind v3 + standard PostCSS plugins to avoid native `lightningcss` binary issues on locked-down Windows environments.

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
