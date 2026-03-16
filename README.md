# Conversational Analytics Agent

Governed monorepo for a conversational analytics product aimed at nontechnical users in a banking environment.

Core properties:
- Next.js frontend in `apps/web`
- FastAPI orchestrator in `apps/orchestrator`
- shared API contracts in `packages/contracts`
- semantic-model source of truth in `semantic_model.yaml`
- SQL/data guardrails in `semantic_guardrails.json`
- fast local eval harness in `packages/eval-harness`
- broader Python eval stack in `evaluation/`

The product is optimized for:
- evidence-backed answers
- low-latency streamed UX
- governed SQL generation and execution
- strict auditability for numeric claims

## Repo Structure

```text
/Users/joe/Code/ci_analyst
  apps/
    orchestrator/        Python API and orchestration pipeline
    web/                 Next.js UI
  packages/
    contracts/           Shared request/response and stream contracts
    eval-harness/        Fast local eval runner
  evaluation/            Broader Python/Phoenix eval tooling and datasets
  docs/                  Durable project docs
  semantic_model.yaml    Canonical semantic model
  semantic_guardrails.json
```

## Runtime Modes

- `sandbox`: Anthropic + local Cortex-compatible REST shim + local SQLite data
- `prod-sandbox`: Azure OpenAI + local Cortex-compatible REST shim + local SQLite data
- `prod`: Azure OpenAI + Snowflake Cortex Analyst + Snowflake execution

Use `sandbox` for normal local product work unless you specifically need Azure or real Snowflake wiring.

## Quick Start

Prerequisites:
- Node.js 20+
- Python 3.10+

1. Install Node workspaces:

```bash
cd /Users/joe/Code/ci_analyst
npm ci
```

2. Optionally create a Python virtual environment:

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
```

If `python` is not available, the repo scripts also try `py -3` and `python3`.

3. Install orchestrator Python dependencies:

```bash
npm run setup:orchestrator
```

4. Create or edit the runtime env files:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`
- `/Users/joe/Code/ci_analyst/apps/web/.env.local`

Recommended local sandbox values:

```dotenv
# apps/orchestrator/.env
PROVIDER_MODE=sandbox
ANTHROPIC_API_KEY=<your-key>
```

```dotenv
# apps/web/.env.local
WEB_BACKEND_MODE=orchestrator
ORCHESTRATOR_URL=http://localhost:8787
```

5. Start the local sandbox stack in three terminals:

```bash
npm run dev:sandbox-cortex
```

```bash
npm run dev:orchestrator
```

```bash
npm run dev:web
```

6. Open [http://localhost:3000](http://localhost:3000)

Optional health checks:

```bash
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8787/health
```

## Environment Notes

- The orchestrator auto-loads `/Users/joe/Code/ci_analyst/apps/orchestrator/.env`.
- The web app reads `/Users/joe/Code/ci_analyst/apps/web/.env.local`.
- Root `/Users/joe/Code/ci_analyst/.env` is not used for normal runtime.
- `semantic_model.yaml` is the semantic-model source of truth.
- `semantic_guardrails.json` contains runtime SQL/data guardrails.
- Optional overrides exist for real-provider runs:
  - `SEMANTIC_MODEL_PATH=/absolute/path/to/semantic_model.yaml`
  - `SEMANTIC_POLICY_PATH=/absolute/path/to/semantic_guardrails.json`

## Key Commands

From the repo root:

```bash
npm run setup:orchestrator
npm run setup:evaluation
npm run dev:sandbox-cortex
npm run dev:orchestrator
npm run dev:web
npm run lint
npm run test
npm run build
npm run eval
```

Command meaning:
- `npm run setup:orchestrator`: install Python deps for the FastAPI service
- `npm run setup:evaluation`: install Python deps for the broader eval stack
- `npm run dev:sandbox-cortex`: start the local Cortex-compatible sandbox shim on port `8788`
- `npm run dev:orchestrator`: start the FastAPI orchestrator on port `8787`
- `npm run dev:web`: start the Next.js frontend on port `3000`
- `npm run eval`: run the fast local eval harness against `http://localhost:8787` by default

## Python Dependency Layout

There are two Python projects on purpose:

- `/Users/joe/Code/ci_analyst/apps/orchestrator/pyproject.toml`
  - runtime, test, and local development dependencies for the orchestrator service
- `/Users/joe/Code/ci_analyst/evaluation/pyproject.toml`
  - dependencies for the broader eval stack in `evaluation/`

If you only need to run the app locally, `npm run setup:orchestrator` is usually enough.

If you need the broader Python/Phoenix eval workflow, also install:

```bash
npm run setup:evaluation
```

## Local Testing and Validation

- Unit/integration: `npm run test`
- Lint: `npm run lint`
- Build: `npm run build`
- Fast evals: `npm run eval`
- `npm run eval` targets `http://localhost:8787` unless `EVAL_BASE_URL` is set

Browser testing notes:
- there is no canonical npm Playwright script today
- current Playwright usage is ad hoc and targeted
- treat folders like `.tmp-playwright` and `test-results` as disposable local artifacts, not supported repo structure

For deeper guidance, see:
- `/Users/joe/Code/ci_analyst/docs/testing.md`
- `/Users/joe/Code/ci_analyst/docs/evals.md`
- `/Users/joe/Code/ci_analyst/docs/user-journeys.md`

## Real Provider Setup

For `PROVIDER_MODE=prod`, configure:
- Azure OpenAI variables such as `AZURE_OPENAI_AUTH_MODE`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, and credentials
- Snowflake variables such as `SNOWFLAKE_CORTEX_*`, `SNOWFLAKE_ACCOUNT`, and auth details
- frontend routing:
  - `WEB_BACKEND_MODE=orchestrator`
  - `ORCHESTRATOR_URL=http://localhost:8787`

Primary provider integration points:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/azure_openai.py`
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/anthropic_llm.py`
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/snowflake_cortex.py`
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/sandbox_cortex.py`
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/factory.py`

## Work-Machine Notes

- Prefer `npm ci` over `npm install`.
- Keep secrets in app-level env files only.
- Do not rely on root `.env` for runtime behavior.
- The work machine is a primary target environment; prefer deterministic, low-friction setup.

If you need to pull upstream while preserving local uncommitted work:

```bash
git stash push -u -m "work-local"
git fetch origin
git checkout main
git pull --ff-only origin main
git stash pop
```

## Key Docs

- `/Users/joe/Code/ci_analyst/docs/architecture.md`
- `/Users/joe/Code/ci_analyst/docs/api-contracts.md`
- `/Users/joe/Code/ci_analyst/docs/testing.md`
- `/Users/joe/Code/ci_analyst/docs/evals.md`
- `/Users/joe/Code/ci_analyst/docs/user-journeys.md`
- `/Users/joe/Code/ci_analyst/docs/evaluation-and-tests.md`
- `/Users/joe/Code/ci_analyst/docs/frontend-ux-spec.md`
- `/Users/joe/Code/ci_analyst/docs/prompts-and-policies.md`
- `/Users/joe/Code/ci_analyst/docs/learnings.md`
