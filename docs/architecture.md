# Architecture

Use this file for stable architecture, system boundaries, key modules, and core data flow.

## Purpose

This document explains the stable architecture of the repository so both humans and agents can navigate it reliably.

It describes:
- major boundaries
- important modules
- core data flow
- where key responsibilities live
- where to look before making changes

This is not a scratchpad.
This is not a task log.

---

## System overview

This repo builds a governed conversational analytics product for nontechnical users. A user asks a natural-language question, the system plans the analysis, retrieves governed data, validates the result, and returns an evidence-backed answer through a web UI.

Primary user interactions:
- streamed chat in the web app
- non-stream turn API used by evals and direct checks
- evidence-table and data-explorer inspection
- suggested follow-up questions and trace review

Main technical layers:
- Next.js frontend in `apps/web`
- FastAPI orchestrator in `apps/orchestrator`
- shared contracts in `packages/contracts`
- semantic-model source of truth in repo `semantic_model.yaml`, with supporting package and runtime consumers
- eval harness and broader evaluation tooling in `packages/eval-harness` and `evaluation/`

Most important architectural properties to preserve:
- strict planner / SQL / validation / synthesis boundaries
- governed, evidence-backed answer generation
- semantic-model-driven business meaning
- fast streamed UX for the main product flow

Example maintenance prompt:
- "Explain the main architecture of this repo to a new engineer in 10 bullets."

---

## Data foundation

The pipeline is built around Snowflake Cortex Analyst with `semantic_model.yaml` as the single source of truth for the governed data domain.

The semantic model owns:
- dimensions, measures, and time dimensions
- co-display rules
- query guidance
- verified query patterns

Durable rules:
- no stage should hardcode business logic that belongs in the semantic model
- if a metric definition, co-display rule, or query pattern needs to change, change the YAML rather than patching Python or prompt strings
- derived runtime summaries are consumers of YAML, not competing semantic authorities

Relevance classification is intentionally a two-layer filter:
- the planner does a first-pass relevance classification using a semantic-model summary to catch clearly out-of-domain questions before SQL generation
- the SQL stage can independently classify an individual step as not relevant using the full semantic model, catching edge cases the summary-level pass missed

---

## Major boundaries

### Frontend / UI

- Responsibility: user-facing chat experience, streamed rendering, evidence display, trace display, and returned-data exploration
- Key files:
  - `apps/web/src/app/page.tsx`
  - `apps/web/src/components/agent-workspace.tsx`
  - `apps/web/src/components/evidence-table.tsx`
  - `apps/web/src/components/data-explorer.tsx`
- Important constraints:
  - main UX is the streamed chat flow
  - UI should show direct answer first, then evidence and audit surfaces
  - private chain-of-thought must not be exposed
- Common pitfalls:
  - stale UI state after failed requests
  - malformed or partially handled stream events
  - evidence or table rendering diverging from final response payload

### Backend / API

- Responsibility: HTTP entrypoints, streaming responses, request validation, and orchestration service wiring
- Key files:
  - `apps/orchestrator/app/main.py`
  - `apps/web/src/app/api/chat/route.ts`
  - `apps/web/src/app/api/chat/stream/route.ts`
- Important constraints:
  - orchestrator is the backend system of record for answer generation
  - stream and non-stream paths should stay logically aligned
- Common pitfalls:
  - mismatched request/response shapes between web proxy and orchestrator
  - stream route returning incomplete or malformed NDJSON

### Orchestration / agent layer

- Responsibility: planning, governed retrieval, validation, synthesis, streaming status, and trace assembly
- Key files:
  - `apps/orchestrator/app/services/orchestrator.py`
  - `apps/orchestrator/app/services/dependencies.py`
  - `apps/orchestrator/app/services/stages/`
- Important constraints:
  - planner, SQL, validation, and synthesis have strict non-overlapping roles
  - boundary violations are real bugs, not style issues
- Common pitfalls:
  - planner resolving business terms it should pass through
  - synthesis inventing semantics or operating beyond evidence
  - stage outputs drifting from contracts

Planner, SQL, and synthesizer boundaries are strict:
- Planner:
  - does first-pass relevance classification, task decomposition, and presentation-intent selection
  - does not resolve business terms, interpret metric meaning, write SQL, or add specificity the user did not ask for
- SQL stage:
  - does resolve business terms against the full semantic model, generate governed read-only SQL, make reasonable assumptions, and classify step-level irrelevance
  - does not decompose multi-step questions, narrate results, or alter the received step goal
- Synthesizer:
  - does narrate findings from the evidence layer, build visual configuration from presentation intent, and produce summaries, insights, follow-ups, confidence, and assumptions
  - does not access the semantic model, expose pipeline internals, or recommend actions

### Data access / query generation

- Responsibility: business-term resolution, SQL generation, SQL guardrails, execution, and provider-specific query access
- Key files:
  - `apps/orchestrator/app/services/sql_guardrails.py`
  - `apps/orchestrator/app/services/stages/sql_stage*.py`
  - `apps/orchestrator/app/providers/snowflake_*.py`
  - `apps/orchestrator/app/providers/sandbox_cortex.py`
- Important constraints:
  - SQL must remain governed and read-only
  - business meaning should come from semantic-model artifacts, not hand-coded logic
- Common pitfalls:
  - hardcoding metric meaning in Python
  - leaking provider-specific assumptions into orchestration logic

### Evaluation / benchmarking

- Responsibility: fast local eval feedback, golden-dataset workflows, quality-gate surfaces
- Key files:
  - `packages/eval-harness/src/run-eval.mjs`
  - `packages/eval-harness/datasets/golden-v1.json`
  - `evaluation/golden_examples.yaml`
  - `evaluation/run_experiment.py`
  - `evaluation/quality_gate.py`
- Important constraints:
  - evals should compare expected versus actual outputs
  - prompt and pipeline changes are regression-sensitive
- Common pitfalls:
  - treating harness failures as instant proof of a product bug
  - mixing eval workflow concerns into general testing docs or product logic

### Testing / Playwright

- Responsibility: unit, stage, integration, and focused browser-flow validation
- Key files:
  - `apps/orchestrator/tests/`
  - `apps/web/src/lib/stream.test.ts`
  - `apps/web/src/components/evidence-table.test.tsx`
  - `.tmp-playwright/`
- Important constraints:
  - no canonical npm Playwright script is currently defined
  - browser-flow checks are useful, but repo state suggests ad hoc Playwright usage rather than a stabilized suite
- Common pitfalls:
  - assuming `.tmp-playwright` is a permanent test subsystem contract
  - using browser checks when the real problem is stage-level or harness-level

### Shared utilities

- Responsibility: shared contracts and shared semantic-model consumers
- Key files:
  - `packages/contracts/src/index.ts`
  - `semantic_model.yaml`
- Important constraints:
  - contracts should stay aligned across web, orchestrator, and eval surfaces
- Common pitfalls:
  - changing one side of a contract without updating the others

### Configuration / environment

- Responsibility: runtime mode selection, env loading, and interpreter/tooling entrypoints
- Key files:
  - `package.json`
  - `apps/orchestrator/package.json`
  - `apps/web/package.json`
  - `apps/orchestrator/.env`
  - `apps/web/.env.local`
- Important constraints:
  - provider mode should be a configuration choice, not an orchestration rewrite
  - work-machine setup should stay deterministic and cross-platform where practical
- Common pitfalls:
  - documenting or assuming commands that are not actually wired in package scripts
  - setup/runtime drift between Python install path and execution path

---

## Key modules and entry points

### `apps/web/src/components/agent-workspace.tsx`
- Role: main chat workspace, stream consumption, summary/evidence rendering entrypoint
- Important dependencies:
  - `apps/web/src/lib/stream.ts`
  - `apps/web/src/components/evidence-table.tsx`
  - `apps/web/src/components/data-explorer.tsx`
- Typical changes made here:
  - response rendering
  - streamed state handling
  - visible product behavior changes
- Risks / gotchas:
  - easy to break loading/error/completed state transitions
  - easy to drift from backend response contracts

### `apps/web/src/app/api/chat/stream/route.ts`
- Role: web-side stream proxy to the orchestrator
- Important dependencies:
  - `@ci/contracts`
  - `apps/web/src/lib/server-env.ts`
- Typical changes made here:
  - request validation
  - proxy behavior
  - stream header handling
- Risks / gotchas:
  - malformed NDJSON handling
  - mismatched behavior versus non-stream route

### `apps/orchestrator/app/main.py`
- Role: FastAPI entrypoint for health, turn, and stream routes
- Important dependencies:
  - `apps/orchestrator/app/services/orchestrator.py`
  - `apps/orchestrator/app/models.py`
- Typical changes made here:
  - route-level request/response behavior
  - stream response behavior
  - top-level middleware/logging changes
- Risks / gotchas:
  - breaking both product flows and eval harnesses at once

### `apps/orchestrator/app/services/orchestrator.py`
- Role: end-to-end turn execution and stream emission
- Important dependencies:
  - `apps/orchestrator/app/services/dependencies.py`
  - `apps/orchestrator/app/services/stages/`
  - `apps/orchestrator/app/evaluation/inline_checks.py`
- Typical changes made here:
  - orchestration sequencing
  - status messages
  - final response shaping
- Risks / gotchas:
  - subtle boundary regressions across planner, SQL, validation, and synthesis
  - easy to affect both streaming UX and non-stream eval paths

### `apps/orchestrator/app/services/stages/`
- Role: stage-specific planner, SQL, validation, summarization, and synthesis logic
- Important dependencies:
  - prompt templates
  - semantic-model services
  - provider protocols
- Typical changes made here:
  - stage contract enforcement
  - prompt/context wiring
  - domain-specific reasoning behavior
- Risks / gotchas:
  - stage overreach
  - hidden semantic logic in the wrong layer

### `apps/orchestrator/app/services/semantic_model.py`
- Role: runtime semantic-model loading and summary helpers
- Important dependencies:
  - `semantic_model.yaml`
- Typical changes made here:
  - deriving runtime-consumable semantic context from YAML
  - planner-context summarization
- Risks / gotchas:
  - drifting away from the YAML source of truth
  - turning derived runtime views into a second semantic authority

### `apps/orchestrator/app/services/semantic_model_yaml.py`
- Role: helper logic around repo `semantic_model.yaml`
- Important dependencies:
  - `semantic_model.yaml`
- Typical changes made here:
  - YAML-term extraction
  - YAML-based prompt context
- Risks / gotchas:
  - semantic meaning should be changed in YAML, not patched into prompts or Python

### `apps/orchestrator/app/providers/factory.py`
- Role: provider-mode selection and bundle assembly
- Important dependencies:
  - provider implementations in `apps/orchestrator/app/providers/`
- Typical changes made here:
  - mode wiring
  - provider swaps
- Risks / gotchas:
  - mode-specific behavior leaking into orchestration layers

### `packages/eval-harness/src/run-eval.mjs`
- Role: fast local eval runner against `/v1/chat/turn`
- Important dependencies:
  - `packages/eval-harness/src/score.mjs`
  - `packages/eval-harness/datasets/golden-v1.json`
- Typical changes made here:
  - eval input/output handling
  - assertion scoring
- Risks / gotchas:
  - easy to misread harness behavior as full release-quality evaluation policy

---

## Core data flow

### User question to streamed answer

1. user submits a question in the web app
2. `apps/web/src/app/api/chat/stream/route.ts` validates and proxies the request
3. `apps/orchestrator/app/main.py` receives the stream request
4. `apps/orchestrator/app/services/orchestrator.py` runs planner, SQL, validation, and synthesis stages
5. stream events are emitted as status updates, answer deltas, and final response
6. `apps/web/src/components/agent-workspace.tsx` renders the stream and hydrates the final structured UI

Where control begins:
- `apps/web/src/components/agent-workspace.tsx`

Where decisions are made:
- stage logic under `apps/orchestrator/app/services/stages/`

Where validation happens:
- request validation at the web/API boundary
- deterministic checks in the validation stage and inline checks

Where failures commonly surface:
- stream parsing and UI state transitions
- SQL-stage blocking or execution issues
- synthesis-contract drift

### User question to non-stream answer

1. user or harness calls `/api/chat` or `/v1/chat/turn`
2. request reaches `apps/orchestrator/app/main.py`
3. `apps/orchestrator/app/services/orchestrator.py` returns a single payload

This path matters because evals depend on it even when the UI primarily uses streaming.

### Eval input to report

1. eval runner loads dataset
2. runner calls `/v1/chat/turn`
3. response is scored against expected tokens, numeric assertions, and latency
4. report is emitted as pass/fail summary

Where failures commonly surface:
- contract drift
- expected-vs-actual mismatch
- environment or service availability

---

## Architectural constraints

- Product operates in a governed corporate banking environment.
- The system must describe what the data shows without becoming prescriptive.
- Auditability and groundedness outrank narrative polish.
- Planner, SQL, validation, and synthesis responsibilities remain separate.
- Semantic-model artifacts should own business-domain meaning.
- `semantic_model.yaml` is the canonical semantic source of truth; runtime helpers may derive consumable views from it but should not become competing authorities.
- LLMs should decide semantics; deterministic code should enforce safety, validity, and interface contracts.
- Resolve intent, scope, and entities once, then propagate them without stage-by-stage reinterpretation.
- Cross-stage context should stay explicit, structured, portable, and machine-readable.
- Preserve the canonical request flow rather than introducing alternate hidden paths.
- Prefer one canonical current-state implementation over compatibility layers.
- Prefer fail-fast diagnostics and explicit recovery steps over silent degraded behavior.
- Prefer reusable general capabilities over hardcoded or overfit logic.
- Core execution and validation should remain deterministic even when model reasoning is probabilistic at the edges.
- Trustworthiness and correctness outrank narrative polish.
- Latency is a real product constraint, especially for streamed responses.
- Extend contracts and interfaces where possible instead of rewriting stage architecture.

---

## Pattern reuse guidance

Before inventing a new pattern:
- search for an existing implementation in this repo
- prefer consistency over novelty
- inspect adjacent files in the same subsystem first

Local canonical patterns already visible in this repo:
- web routes proxy to orchestrator rather than re-implementing backend logic
- orchestration responsibilities are stage-based under `apps/orchestrator/app/services/stages/`
- fast local evals use `packages/eval-harness`

---

## Risk areas

### Orchestration and stage boundaries

- What can go wrong:
  - planner or synthesis overreach
  - hidden business logic in the wrong layer
- What must be validated:
  - stage-specific tests
  - representative end-to-end flow

### Query generation and data retrieval

- What can go wrong:
  - unsafe or semantically wrong SQL
  - provider-specific assumptions leaking upward
- What must be validated:
  - SQL guardrail behavior
  - relevant orchestrator tests
  - answer grounding against returned data

### Answer synthesis and grounding

- What can go wrong:
  - claims unsupported by evidence
  - confidence or assumptions drifting from retrieved data
- What must be validated:
  - synthesis-related tests
  - relevant eval cases

### UI state transitions

- What can go wrong:
  - stale error/loading/completed states
  - streamed and final payload rendering mismatch
- What must be validated:
  - frontend tests
  - focused browser/user-journey checks

### Evaluation surfaces

- What can go wrong:
  - misclassifying harness issues as product regressions
  - changing prompts or contracts without regression coverage
- What must be validated:
  - relevant eval run
  - expected-vs-actual inspection

### Semantic-model integrity

- What can go wrong:
  - runtime consumers drifting away from the YAML source of truth
  - derived semantic views being edited as if they were the primary model
  - semantics patched in Python instead of source-of-truth artifacts
- What must be validated:
  - affected semantic-model consumers
  - planner/SQL behavior for changed business terms

---

## Architecture update rule

Update this doc when:
- a major module boundary changes
- the canonical data flow changes
- an important new subsystem is introduced
- a local pattern becomes the preferred standard

Do not update this doc for minor one-off tasks unless they change durable architecture knowledge.
