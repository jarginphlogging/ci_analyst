# API Contracts

## Orchestrator Base

Default: `http://localhost:8787`

## POST `/v1/chat/turn`

Request:
```json
{
  "sessionId": "optional-uuid",
  "message": "What changed in charge-off risk this quarter?",
  "role": "analyst",
  "explicitFilters": {
    "region": ["NA", "EMEA"]
  }
}
```

Response:
```json
{
  "turnId": "uuid",
  "createdAt": "2026-02-16T19:00:00.000Z",
  "response": {
    "answer": "...",
    "confidence": "high",
    "whyItMatters": "...",
    "metrics": [],
    "evidence": [],
    "insights": [],
    "suggestedQuestions": [],
    "assumptions": [],
    "trace": [],
    "dataTables": [
      {
        "id": "charge_off_drivers",
        "name": "Charge-Off Driver Breakdown",
        "columns": ["segment", "prior", "current", "changeBps", "contribution"],
        "rows": [],
        "rowCount": 0,
        "description": "Segment-level decomposition used in the analysis narrative.",
        "sourceSql": "SELECT ..."
      }
    ]
  }
}
```

## POST `/v1/chat/stream`

Request body is the same as `/v1/chat/turn`.

Response stream content-type:
- `application/x-ndjson`

Event shapes:
```json
{"type":"status","message":"..."}
{"type":"answer_delta","delta":"token "}
{"type":"response","response":{}}
{"type":"done"}
{"type":"error","message":"..."}
```

## GET `/health`

Response:
```json
{
  "status": "ok",
  "timestamp": "...",
  "providerMode": "mock|sandbox|prod"
}
```

## Sandbox Pseudo-Cortex API (Local, default `http://localhost:8788`)

### POST `/api/v2/cortex/analyst/message`

Request:
```json
{
  "conversationId": "session-123",
  "message": "What were my sales by state in Q4 2025?",
  "history": ["Show me channel mix first"],
  "route": "deep_path",
  "stepId": "step_1"
}
```

Response:
```json
{
  "type": "answer|clarification",
  "conversationId": "session-123",
  "sql": "SELECT ...",
  "lightResponse": "One-sentence analyst summary.",
  "clarificationQuestion": "",
  "rows": [],
  "rowCount": 0,
  "assumptions": []
}
```

Notes:
- `type=clarification` returns a non-empty `clarificationQuestion`.
- Service keeps conversation memory by `conversationId`.

### GET `/api/v2/cortex/analyst/history/{conversationId}`

Response:
```json
{
  "conversationId": "session-123",
  "history": ["..."]
}
```

### POST `/api/v2/cortex/analyst/query`

Raw SQL execution endpoint used by the sandbox SQL adapter.

## Frontend API Routes

- `/api/chat` -> turn route (proxy/fallback)
- `/api/chat/stream` -> stream route (proxy/fallback)

Both routes support:
- web mock mode (`WEB_BACKEND_MODE=web_mock`)
- orchestrator proxy mode (`WEB_BACKEND_MODE=orchestrator`, `ORCHESTRATOR_URL` set)
