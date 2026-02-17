# Implementation Blueprint (As Built)

## 1) Repository Structure

```text
/Users/joe/Code/ci_analyst
  apps/
    web/                      # Next.js + Tailwind frontend
    orchestrator/             # Python FastAPI orchestration service
  packages/
    contracts/                # Shared request/response schemas (TypeScript + zod)
    semantic-model/           # Versioned semantic model JSON + validators
    eval-harness/             # Golden-question evaluator
  docs/
```

## 2) Runtime Flow (Turn Execution)

1. Frontend posts a turn to `/api/chat/stream` or `/api/chat`.
2. Web route either:
   - serves local mock stream (`WEB_BACKEND_MODE=web_mock`), or
   - proxies to orchestrator (`WEB_BACKEND_MODE=orchestrator`).
3. Orchestrator receives `/v1/chat/turn` or `/v1/chat/stream`.
4. Dependency mode selected by `PROVIDER_MODE`:
   - `mock` path: deterministic mock provider payloads
   - `sandbox` path: Anthropic + local Cortex REST + local SQLite
   - `prod` path: Azure + Snowflake + guardrails
5. Real path stages:
   - classify route (`fast_path` vs `deep_path`)
   - create bounded plan
   - generate SQL per step
   - run SQL guardrails (allowlist, restricted columns, read-only checks, limit policy)
   - execute SQL via Snowflake adapter
   - validate results
   - synthesize response with deterministic table profiling + Azure narrative
   - carry forward bounded session history into route/plan/sql/response prompts
6. Response is returned with answer, metrics, evidence, insights, trace, assumptions, and `dataTables`.

## 3) Orchestrator Modules (Current)

- Entry/API:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/main.py`
- Core orchestration:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/orchestrator.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/dependencies.py`
- Prompt templates:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/templates.py`
- LLM JSON extraction/parsing:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/llm_json.py`
- Semantic model loading:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/semantic_model.py`
- SQL policy guardrails:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/sql_guardrails.py`
- Result normalization/profiling:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/table_analysis.py`
- Provider adapters:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/azure_openai.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/anthropic_llm.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/snowflake_cortex.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/providers/sandbox_cortex.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/sandbox/cortex_service.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/sandbox/sqlite_store.py`

## 4) Semantic Model

- Current semantic model source: JSON
  - `/Users/joe/Code/ci_analyst/packages/semantic-model/models/banking-core.v1.json`
- Optional runtime override:
  - `SEMANTIC_MODEL_PATH=/absolute/path/to/model.json`
- Policy fields used at runtime:
  - `restrictedColumns`
  - `defaultRowLimit`
  - `maxRowLimit`

## 5) Frontend Integration Contract

- Internal frontend routes:
  - `POST /api/chat`
  - `POST /api/chat/stream`
- Orchestrator routes:
  - `GET /health`
  - `POST /v1/chat/turn`
  - `POST /v1/chat/stream` (`application/x-ndjson`)
- Streaming events:
  - `status`
  - `answer_delta`
  - `response`
  - `done`
  - `error`

## 6) Environment Toggles

### Backend (`apps/orchestrator/.env`)
- Auto-loaded at startup.
- Real runtime file is committed and can be edited directly.
- Optional reference templates:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.mock`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.sandbox`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/.env.prod`
- `PROVIDER_MODE=mock|sandbox|prod`
- `USE_MOCK_PROVIDERS=true|false` (backward-compatible fallback if `PROVIDER_MODE` is unset)
- `AZURE_OPENAI_*`
- `ANTHROPIC_*` (sandbox mode)
- `SNOWFLAKE_CORTEX_*`
- `SANDBOX_CORTEX_*`
- `SANDBOX_SQLITE_PATH`, `SANDBOX_SEED_RESET`
- `SEMANTIC_MODEL_PATH` (optional)
- `REAL_FAST_PLAN_STEPS`, `REAL_DEEP_PLAN_STEPS`
- `REAL_LLM_TEMPERATURE`, `REAL_LLM_MAX_TOKENS`
- `MOCK_STREAM_STATUS_DELAY_MS`, `MOCK_STREAM_TOKEN_DELAY_MS`, `MOCK_STREAM_RESPONSE_DELAY_MS`

### Frontend (`apps/web/.env.local`)
- Real runtime file is committed and can be edited directly.
- Optional reference templates:
  - `/Users/joe/Code/ci_analyst/apps/web/.env.web-mock`
  - `/Users/joe/Code/ci_analyst/apps/web/.env.orchestrator`
- `WEB_BACKEND_MODE=web_mock|orchestrator`
- `ORCHESTRATOR_URL=http://localhost:8787`
- `WEB_MOCK_STATUS_DELAY_MS`, `WEB_MOCK_TOKEN_DELAY_MS`, `WEB_MOCK_RESPONSE_DELAY_MS`

## 7) Test Coverage (Current)

- Orchestrator unit and route tests:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/tests/test_orchestrator.py`
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/tests/test_routes.py`
- Real dependency pipeline tests (stubbed Azure/Snowflake):
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/tests/test_real_dependencies.py`
- SQL guardrail tests:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/tests/test_sql_guardrails.py`
- Frontend stream parser tests:
  - `/Users/joe/Code/ci_analyst/apps/web/src/lib/stream.test.ts`
- Eval harness scoring tests:
  - `/Users/joe/Code/ci_analyst/packages/eval-harness/src/score.test.mjs`

## 8) Known Gaps / Next Hardening Steps

1. Tune prompts with bank-specific language and domain rubric.
2. Align Snowflake adapter payload format to enterprise wrapper if it differs from `/query`.
3. Add CI gate wiring to fail merges when eval regression thresholds are breached.
