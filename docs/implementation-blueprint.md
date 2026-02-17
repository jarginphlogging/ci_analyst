# Implementation Blueprint

## 1) Proposed Repository Structure

```text
/Users/joe/Code/ci_analyst
  apps/
    web/                      # Next.js + Tailwind frontend
    orchestrator/             # API/orchestration service (Python/FastAPI)
  packages/
    contracts/                # Shared types and API contracts
    semantic-model/           # Versioned semantic definitions + validators
    eval-harness/             # Offline + CI evaluation runner
    ui/                       # Shared UI primitives
  docs/
    conversational-analytics-master-plan.md
    implementation-blueprint.md
    prompts-and-policies.md
```

## 2) Runtime Flow (Turn Execution)

1. Frontend posts turn to orchestrator.
2. Orchestrator loads session state and semantic model version.
3. Classifier decides `fast_path` or `deep_path`.
4. Planner builds one or more analysis steps.
5. SQL steps execute through Cortex Analyst REST API.
6. Validator checks numeric integrity and quality flags.
7. Insight engine computes and ranks additional findings.
8. Response generator produces final user-facing output.
9. Trace and metrics are written for observability/evaluation.

## 3) API Contract Drafts

## POST `/api/chat/turn`

```json
{
  "sessionId": "uuid",
  "message": "How did card charge-off rates change in Q4 by region?",
  "role": "analyst",
  "explicitFilters": {
    "region": ["NA", "EMEA"]
  }
}
```

## 200 Response

```json
{
  "sessionId": "uuid",
  "turnId": "uuid",
  "answer": {
    "text": "Charge-off rate rose 42 bps in Q4, mostly driven by NA unsecured cards.",
    "confidence": "high"
  },
  "evidence": {
    "metrics": [
      {"name": "charge_off_rate", "value": 0.0242, "delta": 0.0042}
    ],
    "table": {"columns": ["region", "q3", "q4", "delta_bps"], "rows": []},
    "charts": [{"type": "line", "spec": {}}]
  },
  "insights": [
    {
      "title": "NA drove 78% of deterioration",
      "detail": "Unsecured segment concentration increased materially",
      "priority": 1
    }
  ],
  "assumptions": ["Using booked balance-weighted rate"],
  "suggestedQuestions": [
    "Which products contributed most to the NA increase?",
    "How does this compare with the same quarter last year?",
    "Was the increase driven by volume or severity?"
  ],
  "traceId": "uuid",
  "latencyMs": 2890
}
```

## 4) Frontend Build Plan (Next.js + Tailwind)

### Sprint A
- Scaffold app, auth wrapper, and route layout.
- Build chat workspace shell with responsive layout.
- Create message timeline and answer card.

### Sprint B
- Add evidence renderer (table + chart blocks).
- Add insight cards and suggested follow-ups.
- Add filter chip bar and assumption banner.

### Sprint C
- Add trace viewer page (internal roles only).
- Add loading states and progressive response delivery.
- Add error boundaries and policy-safe error messaging.

### UX rules
- Show direct answer in <= 2 lines first.
- Keep each insight card to headline + one supporting sentence.
- Always display data provenance and confidence tier.

## 5) Orchestrator Build Plan

### Modules
- `session-store`
- `classifier`
- `planner`
- `sql-runner` (Cortex Analyst adapter)
- `validator`
- `insight-engine`
- `response-generator`
- `trace-writer`

### Sequence
1. Implement deterministic fast path.
2. Add deep-path step orchestration (max 4 steps initially).
3. Add validator hard-fail/soft-fail semantics.
4. Add insight engine and ranking.
5. Add policy filters and audit hooks.

## 6) Evaluation and Regression Plan

### Golden dataset v1
- 150 questions total:
  - 60 fast path
  - 60 deep path
  - 30 adversarial/ambiguous

### Automated scoring
- SQL validity
- numeric correctness vs expected tolerances
- latency SLO per path
- insight relevance rubric score
- policy compliance checks

### CI gate recommendation
- Block merge if:
  - numeric correctness drops >1% absolute
  - compliance failures >0
  - p95 latency regresses >20% on benchmark set

## 7) Non-Functional Requirements

- Availability target: 99.9% (business hours priority).
- Trace completeness: 100%.
- PII leakage tolerance: 0 incidents.
- Replay capability for all production turns.

## 8) Immediate Next Tasks (Week 1)

1. Initialize monorepo with `apps/` and `packages/`.
2. Define contracts in `packages/contracts`.
3. Build semantic model schema and sample banking metrics.
4. Scaffold Next.js + Tailwind frontend shell.
5. Implement `/api/chat/turn` with stubbed orchestrator path.
6. Add first 20 golden questions and scoring harness.
