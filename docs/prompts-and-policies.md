# Prompts and Policies Spec

## 1) Prompting Strategy

Use role-specific prompts per stage, not one giant system prompt.

## Stage prompts
- Classifier prompt: classify complexity, ambiguity, and policy risk.
- Planner prompt: produce bounded step plan (max steps, explicit goals).
- Response prompt: convert validated artifacts into concise business narrative.
- Follow-up prompt: generate 3 useful next questions from known context only.

## 2) Deterministic Controls

- Set low temperature for classifier/planner.
- Enforce strict JSON schemas for intermediate outputs.
- Reject and retry invalid schema outputs once; then fail safe.
- Disable unbounded recursion or open tool loops.

## 3) Policy Rules

- Never access data outside allowlisted semantic model.
- Never expose restricted/PII fields in narrative or artifacts.
- Never fabricate missing values; mark unavailable with reason.
- If ambiguity affects correctness, ask a clarification question.

## 4) Confidence Policy

Confidence is based on validation, not language model certainty.

- High: all required QA checks passed, no material assumptions.
- Medium: minor assumptions or soft QA warnings.
- Low: incomplete data, conflicting signals, or unresolved ambiguity.

## 5) Error Handling

- User-safe errors: clear and non-technical.
- Internal traces: include detailed failure taxonomy.
- Return partial validated results when possible.

## 6) Suggested Prompt Skeletons

## Classifier output schema

```json
{
  "route": "fast_path|deep_path",
  "needsClarification": true,
  "clarificationQuestion": "string",
  "policyRisk": "low|medium|high",
  "reason": "string"
}
```

## Planner output schema

```json
{
  "steps": [
    {
      "id": "step_1",
      "goal": "string",
      "inputDependencies": [],
      "expectedOutput": "string"
    }
  ],
  "maxStepsExceeded": false
}
```

## Response output schema

```json
{
  "answer": "string",
  "insights": [
    {"title": "string", "detail": "string", "priority": 1}
  ],
  "assumptions": ["string"],
  "suggestedQuestions": ["string"]
}
```

## 7) Guardrails for Insight Generation

- Insight must reference validated evidence artifact IDs.
- Rank by impact x confidence x user relevance.
- Cap at 3 insights by default to reduce cognitive overload.

## 8) Logging Requirements

For each turn, persist:
- prompt version ids used
- model deployment ids
- intermediate JSON outputs
- SQL request/response ids
- QA outcomes
- final payload and latency

