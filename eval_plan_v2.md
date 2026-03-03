# Cortex Analyst Evaluation Plan v2 — Three-Tier Architecture (Code-Aligned)

## Intent Preservation

This v2 plan preserves the original intent:

- three-tier evaluation architecture
- deterministic + LLM-as-judge evaluation
- runtime inline checks + async production evaluation + golden dataset correctness
- production governance through Phoenix

Only adaptation in v2: align all evaluation design to the real orchestrator stage contracts and trace payloads in this repository.

---

## Core Model (Unchanged)

Each tier has different context and therefore different truth claims.

```
                        Has ground     Can use      Blocks
                        truth?         LLM judge?   response?    Runs when?
                        ─────────      ──────────   ─────────    ──────────
Tier 1: Inline          No             No           Yes          Every request
Tier 2: Async Prod      No             Yes          No           After response
Tier 3: Golden Dataset  Yes            Yes          No           CI/CD + nightly
```

This still means:

- Tier 1 checks structural/runtime safety.
- Tier 2 checks internal consistency.
- Tier 3 checks actual correctness.

---

## Real Pipeline Nodes (v2 Mapping)

Current pipeline contract in code:

```
User Question → [t1 Plan] → [t2 SQL Generation + Execution] → [t3 Validation] → [t4 Synthesis]
```

Where:

- `t1`: planner decision, bounded task plan, presentation intent
- `t2`: per-step SQL generation, guardrails, execution, retry/recovery
- `t3`: deterministic quality checks over SQL outputs
- `t4`: deterministic + LLM synthesis into final response

---

## Tier 1: Inline Checks (Hot Path)

Context: current stage input/output only. No ground truth.
Latency budget: keep added checks lightweight.
Implementation: deterministic Python checks in pipeline path.

### Existing Foundation in Current Code

- SQL guardrails (read-only, allowlist, restricted columns, row limits)
- result validation (non-empty, row limits, null-rate sanity)
- structured response contracts via Pydantic models

### Tier 1 v2 Check Matrix

| Stage | Check | Input/Output Basis | Fail Action |
|------|------|------|------|
| `t1 Plan` | Plan structure sanity | Steps parse and normalize; count in bounded range | Block with planner guidance |
| `t1 Plan` | Intent coherence sanity | Presentation intent enum/shape coherence | Fallback to deterministic default |
| `t2 SQL` | SQL policy validity | Guardrail compliance for each step | Retry/skip step per existing retry policy |
| `t2 SQL` | Execution payload sanity | Row count and payload size sanity per step | Truncate/warn or block per policy |
| `t3 Validation` | Validation pass contract | Validation checks present and pass | Block response |
| `t4 Synthesis` | Output sanity | Non-empty, minimum informational quality | Fallback deterministic narrative |
| `t4 Synthesis` | PII policy scan | SSN/account-like pattern detection in answer | Redact + warning |

### Tier 1 Scope Boundary

Tier 1 can assert safe structure and policy compliance.
Tier 1 cannot assert business correctness of answer content.

---

## Tier 2: Async Production Evaluation (Phoenix)

Context: full pipeline traces/spans and stage payloads, but no ground truth.
Latency impact: zero to user path.
Purpose: internal consistency and quality drift detection in production.
Authority: governance monitoring, not merge gating.

### Judge Context by Stage (No Ground Truth)

| Stage | Judge Input | Judge Question | Evaluator Type |
|------|------|------|------|
| `t1 Plan` | question + produced steps + presentation intent | Do steps cover user intent without redundancy/off-topic drift? | Custom LLM classifier |
| `t2 SQL` | step goal + generated SQL + execution outcomes | Does generated SQL plausibly answer step goal given execution output? | SQL-generation eval |
| `t3 Validation` | deterministic checks and pass/fail signals | Did validation indicate usable data quality? | Deterministic code scoring |
| `t4 Synthesis` | synthesis input context + final answer | Is answer grounded in pipeline-produced data? Does it answer question? | Hallucination + QA eval |

### Critical Meaning at Tier 2

Hallucination and QA judgments here are grounded on pipeline-produced context, not external truth.

So internally consistent but factually wrong pipelines can still pass Tier 2.
That is expected. Tier 3 catches factual wrongness.

### Tier 2 Outputs

- span-level evaluator scores logged to Phoenix
- flagged traces for review:
  - hallucinated
  - SQL incorrect
  - QA incorrect
- weekly failure promotion candidates into golden set

---

## Tier 3: Golden Dataset Evaluation (Phoenix Experiments)

Context: pipeline outputs plus known-correct references.
Latency impact: none on user requests.
Purpose: correctness regression detection and release gating.
Authority: primary merge/release gate.

### Judge Context by Stage (With Ground Truth)

| Stage | Actual Output | Ground Truth | Evaluator Type |
|------|------|------|------|
| `t1 Plan` | actual task plan | expected task decomposition | LLM + deterministic coverage |
| `t2 SQL` | generated SQL per step + execution results | expected SQL and/or expected result sets | SQL LLM eval + deterministic execution accuracy |
| `t3 Validation` | validation checks/pass-fail | expected data quality outcomes | deterministic evaluator |
| `t4 Synthesis` | final answer | expected answer and key facts | QA correctness + hallucination + key-value presence |

### Deterministic + LLM Evaluator Mix

Deterministic examples:

- execution accuracy (result-set comparison)
- decomposition/plan coverage
- must-contain key value presence
- SQL syntax/policy validity

LLM examples:

- SQL correctness given question and context
- summarization/synthesis quality
- hallucination/groundedness
- QA correctness against known reference

---

## Phoenix Authority + Legacy Parallelism

This system runs in dual mode:

- Phoenix evaluations are authoritative governance and release gate.
- Legacy eval harness remains for rapid developer feedback.

### Authority Rules

- Merge/release gate: Phoenix Tier 3 thresholds only.
- Legacy eval results: advisory, fast loop signal.
- If legacy and Phoenix disagree, Phoenix decides release outcome.

---

## CI/CD Quality Gate (Authoritative)

Quality gate checks latest Tier 3 experiment metrics and fails build on regression.

Threshold examples (initial targets):

- execution_accuracy >= 0.80
- decomposition_coverage >= 0.75
- key_value_presence >= 0.85
- sql_syntax_valid >= 0.95
- SQL Correctness (LLM) >= 0.80
- Hallucination (LLM) >= 0.85
- QA Correctness (LLM) >= 0.80
- Summarization/Synthesis Quality (LLM) >= 0.80

Thresholds are tuned after baseline stabilization.

---

## Feedback Flywheel (Unchanged)

1. Tier 2 flags production anomalies.
2. Weekly review confirms true failures.
3. Confirmed failures are promoted to golden dataset.
4. Tier 3 catches that failure class in future PR/nightly runs.

This compounds quality over time.

---

## Implementation Phases (Eval-Focused)

### Phase 0: Contract Lock

- lock `t1..t4` eval data contracts from current runtime outputs
- document exact field mappings for evaluators

### Phase 1: Dual Tracing

- keep existing UI trace output
- add Phoenix trace/span emission in parallel

### Phase 2: Tier 1 Inline Checks

- extend hot-path deterministic checks where gaps remain

### Phase 3: Tier 2 Async Phoenix Evals

- scheduled evaluator runs over recent production traces
- score logging and flagged trace export

### Phase 4: Tier 3 Golden + Experiments

- dataset + deterministic and LLM evaluators
- experiment runner and result storage

### Phase 5: CI Gate (Phoenix Authority)

- PR and nightly quality gate from Tier 3

### Phase 6: Ongoing Calibration

- eval-the-evals monthly
- adjust judge prompts/thresholds by agreement results

---

## Non-Goals in v2

- replacing existing UI trace system
- removing legacy eval harness
- collapsing all evaluation into one tier

v2 is adaptation of the original evaluation intent to the real system contracts, not a strategic rewrite.

