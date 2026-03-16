# Backend

Use this file for the structure, runtime flow, stage boundaries, provider wiring, and major change points of the orchestrator backend.

## Purpose

This document explains how the backend works in this repository.

It should help a new engineer answer:
- what the backend owns
- which files are the real entrypoints
- how a chat turn moves through the pipeline
- where planner, SQL, validation, and synthesis responsibilities live
- how provider mode changes runtime behavior
- where to make changes without violating stage boundaries

This is durable backend architecture documentation.
It is not a task log or a temporary debugging note.

---

## Backend overview

The backend is the orchestrator service in `apps/orchestrator`.

Its job is to:
- accept validated chat requests
- build a bounded analysis plan
- execute governed SQL retrieval
- validate retrieval results
- synthesize a user-facing response from evidence
- stream progress and final output back to the caller

The backend is the system of record for:
- orchestration policy
- stage boundaries
- provider selection
- semantic-model consumption
- SQL guardrails
- response assembly
- audit-oriented trace content

The backend is not responsible for:
- frontend layout or visual rendering
- benchmark orchestration outside its own inline checks
- redefining governed domain meaning outside the semantic model and policy inputs

---

## Environment provider matrix

This repository should be read with the following environment model in mind.

Think about each environment as three provider choices:
- LLM provider
- SQL generation provider
- SQL execution provider

Target environment matrix:

| Environment | LLM provider | SQL generation provider | SQL execution provider |
| --- | --- | --- | --- |
| `prod` | `Azure OpenAI` or `Anthropic via Amazon Bedrock` | `Snowflake Cortex Analyst` | `Snowflake Python Connector` |
| `prod-sandbox` | `Azure OpenAI` or `Anthropic via Amazon Bedrock` | `Cortex Emulator` | `SQLite` |
| `sandbox` | `Anthropic direct API` | `Cortex Emulator` | `SQLite` |

Read the rest of the backend docs using that mental model:
- planner and synthesis use the configured LLM provider
- SQL generation uses either Snowflake Cortex Analyst or the local Cortex emulator
- SQL execution uses either the Snowflake Python Connector or local SQLite execution

Important distinction:
- `sandbox` Anthropic means direct Anthropic API access
- `prod` and `prod-sandbox` Anthropic means Anthropic models accessed through Amazon Bedrock, not direct Anthropic API usage

Important note:
- this section documents the intended environment model for the product
- if current implementation wiring differs temporarily, treat that as implementation drift to resolve rather than as the desired long-term backend shape

---

## Backend runtime entrypoints

### `apps/orchestrator/app/main.py`

This is the primary HTTP entrypoint.

It owns:
- FastAPI app construction
- logging/tracing initialization
- request logging middleware
- the `/health` route
- the synchronous turn route
- the streaming turn route

Important routes:
- `GET /health`
  - returns status, timestamp, and provider mode
- `POST /v1/chat/turn`
  - returns one JSON response payload
- `POST /v1/chat/stream`
  - returns NDJSON stream events

Important startup behavior:
- logging is configured up front
- tracing is initialized up front
- `ConversationalOrchestrator(create_dependencies())` is instantiated at module load

This means:
- the backend is a long-lived process with dependency wiring done at startup
- provider-mode or dependency changes usually require process restart, not per-request dynamic rewiring

---

## Request and response models

Key file:
- `apps/orchestrator/app/models.py`

This file defines the backend’s Pydantic model layer.

It owns:
- input request models
- response payload models
- trace models
- metric/evidence/insight models
- chart/table configuration models
- synthesis context support models

Important top-level models:
- `ChatTurnRequest`
- `AgentResponse`
- `TurnResult`
- `TraceStep`
- `SqlExecutionResult`
- `ValidationResult`
- `PresentationIntent`
- `TemporalScope`

Contract relationship:
- the backend model layer and `packages/contracts` should stay aligned
- backend Pydantic models are the server-side runtime contract
- `packages/contracts` is the shared web/backend TypeScript contract

If these drift, the most common visible failures are:
- frontend rendering gaps
- stream parsing errors
- broken tests in web or eval harness

---

## Configuration and environment

Key file:
- `apps/orchestrator/app/config.py`

This file loads and normalizes backend runtime settings.

What it does:
- loads `.env` from `apps/orchestrator/.env` if available
- defines typed settings for provider mode, model/provider credentials, semantic-model paths, policy paths, SQL limits, and LLM behavior

Important settings families:
- service runtime
  - `PORT`
  - `LOG_LEVEL`
- provider mode
  - `PROVIDER_MODE`
- Azure OpenAI
  - endpoint, deployment, auth mode, keys/cert inputs
- Anthropic
  - base URL, API key, model
- Snowflake Cortex / analyst
  - base URL, auth inputs, semantic references
- Snowflake connector SQL
  - account/user/auth/warehouse/database/schema
- sandbox runtime
  - sandbox cortex URL
  - sandbox SQLite path
  - timeout values
- semantic inputs
  - `SEMANTIC_MODEL_PATH`
  - `SEMANTIC_POLICY_PATH`

Important normalization:
- provider mode resolves to one of:
  - `sandbox`
  - `prod`
  - `prod-sandbox`
- unknown values normalize to `sandbox`

Important operational rule:
- setup and runtime should use the same interpreter and env assumptions
- if a backend environment change is needed, prefer changing configuration rather than branching orchestration logic

---

## Provider modes and dependency wiring

Key files:
- `apps/orchestrator/app/providers/factory.py`
- `apps/orchestrator/app/providers/protocols.py`
- `apps/orchestrator/app/services/dependencies.py`

### Provider protocols

The backend abstracts providers through three callable protocol surfaces:
- `LlmFn`
  - structured prompt/response model calls
- `SqlFn`
  - SQL execution calls returning rows
- `AnalystFn`
  - analyst-oriented message-to-SQL guidance calls

### Provider bundle factory

`build_provider_bundle` selects runtime providers from provider mode.

Current modes:
- `sandbox`
  - LLM: Anthropic direct API
  - SQL generation: Cortex Emulator
  - SQL execution: SQLite
- `prod`
  - LLM: Azure OpenAI or Anthropic via Amazon Bedrock
  - SQL generation: Snowflake Cortex Analyst
  - SQL execution: Snowflake Python Connector
- `prod-sandbox`
  - LLM: Azure OpenAI or Anthropic via Amazon Bedrock
  - SQL generation: Cortex Emulator
  - SQL execution: SQLite

This design lets the same orchestration pipeline run against different execution backends without rewriting stage logic.

### RealDependencies

`RealDependencies` in `services/dependencies.py` wires the stage objects together:
- `PlannerStage`
- `SqlExecutionStage`
- `ValidationStage`
- `SynthesisStage`

It also owns:
- semantic-model loading
- semantic-policy loading
- structured LLM call wrapping
- provider trace capture for LLM calls

This is the main composition root for the backend pipeline.

---

## Core backend flow

The orchestrator backend uses a stage pipeline.

High-level turn lifecycle:

1. `main.py` receives a validated `ChatTurnRequest`
2. `ConversationalOrchestrator.run_turn` or `.stream_events` is called
3. prior session history is retrieved and updated
4. planner stage creates a bounded analysis plan
5. SQL stage resolves terms and executes governed SQL retrieval
6. validation stage checks retrieval results
7. synthesis stage builds the final response payload
8. trace and inline-check information are attached
9. the backend returns either:
   - one JSON `TurnResult`
   - or a stream of NDJSON events ending in the final response

The pipeline is stage-based, not a monolithic “ask model once” flow.

---

## ConversationalOrchestrator

Key file:
- `apps/orchestrator/app/services/orchestrator.py`

This is the runtime coordinator for chat turns.

It owns:
- session history bookkeeping
- streamed progress messaging
- orchestration sequencing
- inline sanity checks
- trace summarization
- run-turn and stream-events interfaces

Important methods:
- `_session_context`
  - manages per-session recent history
- `_execute_pipeline`
  - runs plan, SQL, validation, and response-building stages
- `run_turn`
  - executes the non-stream path
- `stream_events`
  - executes the stream path and emits NDJSON-compatible event dicts

Important internal concerns:
- stage timing capture
- progress-message sanitization for client display
- blocked-error handling
- trace and check recording

Important state:
- `_session_history`
  - backend-side recent-turn memory by session ID
- `_latest_inline_checks`
  - latest stage check summaries for trace/reporting

This file is the best place to inspect if:
- streaming behavior changed
- stage timing/progress behavior changed
- blocked flows are behaving incorrectly
- trace summaries no longer match actual stage execution

---

## Stage boundaries

The backend is intentionally split into planner, SQL, validation, and synthesis stages.

This separation is not cosmetic. It is policy.

### Planner stage

Key file:
- `apps/orchestrator/app/services/stages/planner_stage.py`

Primary role:
- first-pass relevance classification
- bounded decomposition into executable steps
- presentation-intent selection
- temporal-scope extraction

Important inputs:
- user message
- bounded prior history
- semantic-model summary

Important outputs:
- `PlannerDecision`
- executable `QueryPlanStep` list
- `PresentationIntent`
- optional `TemporalScope`

Important rules:
- planner uses a semantic-model summary, not the full semantic-model authority for business-term resolution
- planner can block the turn when the request is clearly out of domain or too complex
- planner should not invent extra specificity or semantic interpretation that belongs in the SQL stage

Failure/blocked modes:
- `out_of_domain`
- `too_complex`
- general planner LLM failure

### SQL stage

Key files:
- `apps/orchestrator/app/services/stages/sql_stage.py`
- `apps/orchestrator/app/services/stages/sql_stage_generation.py`
- `apps/orchestrator/app/services/stages/sql_state_machine.py`
- `apps/orchestrator/app/services/sql_guardrails.py`

Primary role:
- resolve business terms against the full semantic model
- generate governed SQL per plan step
- enforce SQL guardrails
- execute SQL
- capture retry feedback and step-level assumptions/caveats

Important inputs:
- original user message
- plan steps
- history
- temporal scope
- dependency context from earlier steps where needed
- semantic model
- semantic policy

Important outputs:
- `SqlExecutionResult` list
- retry feedback
- interpretation notes
- caveats
- assumptions

Important rules:
- SQL must be read-only
- SQL must reference allowlisted tables
- restricted columns must be blocked
- row limits must be enforced
- the SQL stage may classify a step as irrelevant or blocked even after planner approval

Important implementation detail:
- the SQL stage has dependency-context compaction logic so later steps can use bounded outputs from earlier steps without exploding context size

### Validation stage

Key file:
- `apps/orchestrator/app/services/stages/validation_stage.py`

Primary role:
- validate the SQL stage’s retrieval outputs before synthesis

Current checks include:
- at least one SQL step ran
- total rows retrieved is non-zero
- no step exceeds max row limit
- observed null rate is below a high-failure threshold
- restricted-column access is assumed prevented upstream by guardrails

Important characteristic:
- this stage is intentionally small and deterministic

### Synthesis stage

Key file:
- `apps/orchestrator/app/services/stages/synthesis_stage.py`

Primary role:
- convert validated retrieval results into the final `AgentResponse`

It builds:
- answer text
- why-it-matters
- summary cards
- evidence rows
- insights
- suggested questions
- assumptions
- data tables
- artifacts
- facts and comparisons
- headline and evidence references
- presentation configuration

Important rule:
- synthesis works from a synthesized context package built from execution outputs
- it should not become a backdoor semantic-model interpreter

Important implementation detail:
- `DataSummarizerStage` contributes compact summaries of result tables for synthesis context
- the stage builds a `SynthesisContextPackage` so the final narration is based on bounded structured evidence rather than raw result dumping

---

## Semantic inputs

The backend consumes two different but related semantic inputs.

### Semantic model

Key files:
- `semantic_model.yaml`
- `apps/orchestrator/app/services/semantic_model.py`
- `apps/orchestrator/app/services/semantic_model_yaml.py`

Role:
- business-domain meaning
- planner summary generation
- SQL-stage semantic grounding

Important rule:
- `semantic_model.yaml` is the source of truth for domain meaning
- derived runtime helpers should consume it, not replace it

### Semantic policy

Key files:
- `apps/orchestrator/app/services/semantic_policy.py`
- `apps/orchestrator/app/services/sql_guardrails.py`
- runtime-discovered semantic guardrails JSON referenced by `SEMANTIC_POLICY_PATH` or discovered by `semantic_policy.py`

Role:
- table allowlist
- restricted columns
- default row limit
- max row limit

Important distinction:
- semantic model is domain meaning
- semantic policy is guardrail/configuration input for governed retrieval

Do not collapse these concepts into one in code or docs.

---

## Prompt and structured LLM behavior

Key files:
- `apps/orchestrator/app/prompts/templates.py`
- `apps/orchestrator/app/prompts/markdown/*.md`
- `apps/orchestrator/app/services/llm_json.py`
- `apps/orchestrator/app/services/llm_schemas.py`
- `apps/orchestrator/app/services/llm_trace.py`

How it works:
- stage-specific prompts are rendered from markdown templates
- `RealDependencies` calls providers in structured-output mode where supported
- payloads are parsed and validated into Pydantic models
- LLM traces are recorded for observability

Important boundary:
- prompt helpers are supporting infrastructure
- the durable operational entrypoints are still the stage classes, not the prompt-helper file

If you change prompting behavior:
- inspect the relevant stage first
- then inspect the prompt templates
- then inspect the structured schema and parser behavior

---

## Streaming behavior

The backend stream path is implemented in:
- `apps/orchestrator/app/main.py`
- `apps/orchestrator/app/services/orchestrator.py`

The HTTP layer emits NDJSON lines.

The orchestrator produces event dictionaries with types such as:
- `status`
- `answer_delta`
- `response`
- `done`
- `error`

Important behavior:
- the stream path validates event payload shape at the HTTP edge before yielding known event types
- on exceptions, the backend emits an `error` event followed by `done`

Important implication:
- the frontend depends on the stream path being line-delimited JSON and event-type stable

If streaming changes:
- validate both the backend NDJSON output and the frontend parser

---

## Observability and tracing

Key files:
- `apps/orchestrator/app/observability.py`
- `apps/orchestrator/app/tracing.py`
- `apps/orchestrator/app/services/llm_trace.py`
- `apps/orchestrator/app/evaluation/inline_checks.py`

The backend records:
- request-level logs
- request IDs
- session IDs
- stage timing
- inline sanity checks
- LLM prompt/response traces
- stage input/output trace payloads

Important uses:
- auditability
- debugging
- explaining failures or blocked steps
- exposing structured trace content to the frontend

Important rule:
- observability should help explain the pipeline without turning into hidden alternate logic

---

## Health, sessions, and state

### Health

`GET /health` exposes:
- service status
- timestamp
- provider mode

This is intentionally lightweight.

### Session history

The orchestrator keeps a bounded in-memory session history in `ConversationalOrchestrator`.

Current behavior:
- history is keyed by session ID
- only a bounded recent window is retained
- the backend uses this prior history during planning and synthesis prompt construction

Important implication:
- session memory is process-local
- it is not durable persistence
- restarting the orchestrator resets in-memory history

---

## Backend file map by concern

### HTTP and runtime bootstrap
- `apps/orchestrator/app/main.py`
- `apps/orchestrator/app/config.py`

### Models and contracts
- `apps/orchestrator/app/models.py`
- `packages/contracts/src/index.ts`

### Orchestration control
- `apps/orchestrator/app/services/orchestrator.py`
- `apps/orchestrator/app/services/dependencies.py`
- `apps/orchestrator/app/services/types.py`

### Stage implementations
- `apps/orchestrator/app/services/stages/planner_stage.py`
- `apps/orchestrator/app/services/stages/sql_stage.py`
- `apps/orchestrator/app/services/stages/sql_stage_generation.py`
- `apps/orchestrator/app/services/stages/sql_state_machine.py`
- `apps/orchestrator/app/services/stages/validation_stage.py`
- `apps/orchestrator/app/services/stages/synthesis_stage.py`
- `apps/orchestrator/app/services/stages/data_summarizer_stage.py`

### Semantic inputs and guardrails
- `apps/orchestrator/app/services/semantic_model.py`
- `apps/orchestrator/app/services/semantic_model_yaml.py`
- `apps/orchestrator/app/services/semantic_policy.py`
- `apps/orchestrator/app/services/sql_guardrails.py`
- `semantic_model.yaml`

### Providers
- `apps/orchestrator/app/providers/factory.py`
- `apps/orchestrator/app/providers/protocols.py`
- `apps/orchestrator/app/providers/azure_openai.py`
- `apps/orchestrator/app/providers/anthropic_llm.py`
- `apps/orchestrator/app/providers/sandbox_cortex.py`
- `apps/orchestrator/app/providers/snowflake_analyst.py`
- `apps/orchestrator/app/providers/snowflake_connector_sql.py`
- `apps/orchestrator/app/providers/snowflake_cortex.py`

### Observability and checks
- `apps/orchestrator/app/observability.py`
- `apps/orchestrator/app/tracing.py`
- `apps/orchestrator/app/services/llm_trace.py`
- `apps/orchestrator/app/evaluation/inline_checks.py`

---

## Common change scenarios

### Change HTTP behavior or streaming response shape

Start with:
- `apps/orchestrator/app/main.py`
- `apps/orchestrator/app/models.py`
- `packages/contracts/src/index.ts`

### Change planning behavior

Start with:
- `apps/orchestrator/app/services/stages/planner_stage.py`
- relevant planner prompt templates under `app/prompts/markdown/`

### Change SQL generation or execution behavior

Start with:
- `apps/orchestrator/app/services/stages/sql_stage.py`
- `apps/orchestrator/app/services/stages/sql_stage_generation.py`
- `apps/orchestrator/app/services/sql_guardrails.py`
- semantic inputs if the change is domain-definition driven

### Change validation rules

Start with:
- `apps/orchestrator/app/services/stages/validation_stage.py`

### Change final response assembly or explanation behavior

Start with:
- `apps/orchestrator/app/services/stages/synthesis_stage.py`
- `apps/orchestrator/app/services/stages/data_summarizer_stage.py`
- `apps/orchestrator/app/models.py`

### Change provider wiring or deployment mode

Start with:
- `apps/orchestrator/app/config.py`
- `apps/orchestrator/app/providers/factory.py`
- the specific provider module

---

## Risk areas

### Stage-boundary drift

What can go wrong:
- planner starts interpreting semantic meaning it should pass through
- SQL stage starts rewriting user goals
- synthesizer starts acting like a semantic-model consumer

What to validate:
- boundary-sensitive tests
- traces from representative turns
- output quality after prompt or stage logic changes

### Contract drift

What can go wrong:
- backend Pydantic models and shared TS contracts diverge
- stream event shapes change without frontend updates

What to validate:
- web integration
- stream parsing
- non-stream response rendering

### Semantic drift

What can go wrong:
- domain meaning gets patched into Python instead of YAML
- semantic policy and semantic model are conflated

What to validate:
- YAML-driven behavior
- affected planner/SQL/eval paths

### Provider-mode divergence

What can go wrong:
- sandbox and production paths drift unintentionally
- mixed-mode assumptions leak into stage logic

What to validate:
- provider-mode-specific smoke checks
- route behavior and trace behavior in the intended mode

### Observability becoming misleading

What can go wrong:
- traces no longer correspond to real stage execution
- inline checks report stale or partial information

What to validate:
- representative traces
- blocked and failed flows
- stage timing/reporting consistency

---

## Relationship to other docs

Use this doc together with:
- `docs/architecture.md`
  - repo-wide system boundaries across frontend, backend, and evaluation
- `docs/testing.md`
  - validation strategy and commands
- `docs/evals.md`
  - benchmark and regression workflows
- `docs/user-journeys.md`
  - visible product flows that the backend ultimately powers
- `docs/api-contracts.md`
  - wire-format and contract expectations

This backend doc is specifically for understanding the orchestrator service itself.

---

## Update rule

Update this document when:
- the backend request lifecycle changes
- stage ownership changes
- provider-mode wiring changes
- semantic input handling changes
- major API routes or response shapes change

Do not update it for isolated bug fixes unless they changed durable backend behavior or boundaries.
