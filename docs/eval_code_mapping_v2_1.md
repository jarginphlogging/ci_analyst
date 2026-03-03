# Eval Code Mapping v2.1 (`t1..t4`)

## Stage Map

| Stage | Runtime location | Input | Output |
|------|------|------|------|
| `t1` plan | `PlannerStage.create_plan` via `RealDependencies.create_plan` | `ChatTurnRequest.message`, bounded `history` | `TurnExecutionContext.plan`, `presentation_intent` |
| `t2` SQL generation + execution | `SqlExecutionStage.run_sql` via `RealDependencies.run_sql` | `message`, `route`, plan steps, retry feedback | `list[SqlExecutionResult]`, retry feedback, assumptions |
| `t3` validation | `ValidationStage.validate_results` via `RealDependencies.validate_results` | `list[SqlExecutionResult]` | `ValidationResult(passed, checks)` |
| `t4` synthesis | `SynthesisStage.build_response` / `build_fast_response` | message, route, plan, results, history | `AgentResponse` |

## Existing Trace Payloads (Preserved)

### UI trace payload

`AgentResponse.trace` entries:

- `id`, `title`, `summary`, `status`
- optional `runtimeMs`, `sql`, `qualityChecks`
- `stageInput: dict`
- `stageOutput: dict`

### LLM trace collector

`LlmTraceCollector.entries` stage names:

- `plan_generation`
- `sql_generation`
- `synthesis_final`

## Phoenix Tracing v2.1

Phoenix spans added in parallel:

- `pipeline.t1_plan`
- `pipeline.t2_sql`
- `pipeline.t3_validation`
- `pipeline.t4_synthesis`

Required span attrs:

- `eval.stage`
- `input.value`
- `output.value`

Stage attrs:

- `t2`: `sql.query`, `result.row_count`, `result.columns`, `retry.count`
- `t3`: `validation.passed`, `validation.check_count`
- `t4`: `response.confidence`, `response.table_count`, `response.artifact_count`

## Inline Check Hooks

Module:

- `apps/orchestrator/app/evaluation/inline_checks_v2_1.py`

Hook points:

- `t1` after plan creation
- `t2` after SQL execution (per step)
- `t3` after validation
- `t4` after response generation (draft/final)

## SQL Provider Wiring

Current runtime:

- SQL execution provider function in `ProviderBundle.sql_fn`
- prod currently points to REST adapter (`execute_cortex_sql`)
- sandbox points to sqlite-backed sandbox execution

Evaluator scripts should use configured execution pathway abstraction, not hardcoded direct DB connector calls.

