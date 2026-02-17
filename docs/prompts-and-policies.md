# Prompts and Policies (Implemented)

## 1) Prompt Stages

The real backend uses stage-specific prompts from:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/prompts/templates.py`

Stages:
1. `route_prompt` -> choose `fast_path` or `deep_path`
2. `plan_prompt` -> generate bounded plan steps
3. `sql_prompt` -> produce one SQL statement per step
4. `response_prompt` -> produce final narrative payload

All stages request strict JSON output and run through parser safeguards.

## 2) LLM Output Enforcement

- Parser implementation:
  - `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/llm_json.py`
- Behavior:
  - attempts JSON extraction from plain or fenced output
  - raises on invalid JSON objects
  - pipeline falls back to deterministic defaults when parsing fails

## 3) SQL Guardrails (Hard Controls)

Implemented in:
- `/Users/joe/Code/ci_analyst/apps/orchestrator/app/services/sql_guardrails.py`

Rules:
- read-only only (`SELECT`/`WITH`)
- reject mutation/DDL statements
- allowlisted table references only (semantic model)
- restricted column blocking
- enforce row-limit policy (default limit added if missing, capped if too high)

## 4) Semantic Policy Source

Loaded from semantic model JSON:
- `/Users/joe/Code/ci_analyst/packages/semantic-model/models/banking-core.v1.json`
- optional override via `SEMANTIC_MODEL_PATH`

Policy fields used in runtime:
- `restrictedColumns`
- `defaultRowLimit`
- `maxRowLimit`

## 5) Confidence and Response Policy

Confidence in the final response is constrained to:
- `high`
- `medium`
- `low`

Response assembly combines:
- deterministic evidence/metric extraction from retrieved rows
- LLM narrative generation constrained to retrieved summaries
- deterministic fallback if LLM fails

## 6) Chain-of-Thought Handling

- UI and APIs expose concise trace summaries (`trace`) and quality checks.
- Private raw chain-of-thought is not exposed.
- SQL text and validations are included for explainability.

## 7) Logging Expectations

Current payload includes:
- per-turn `trace`
- `assumptions`
- `dataTables` with source SQL
- stream status checkpoints

Recommended next step for production:
1. persist prompt version IDs per stage
2. persist model deployment/version
3. persist SQL request/response IDs from enterprise data gateway
4. persist validation outcomes for replay and audits
