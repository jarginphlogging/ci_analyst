# API Contracts

Use this file for request/response payload definitions, contract shapes, and boundary-level API expectations.

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
  "providerMode": "sandbox|prod-sandbox|prod"
}
```

## Sandbox Pseudo-Cortex API (Local, default `http://localhost:8788`)

### GET `/health`

Response:
```json
{
  "status": "ok",
  "database": "/absolute/path/to/sqlite.db",
  "conversationCount": 3
}
```

### POST `/api/v2/cortex/analyst/message`

Request:
```json
{
  "conversationId": "session-123",
  "message": "What were my sales by state in Q4 2025?",
  "history": ["Show me channel mix first"],
  "stepId": "step_1",
  "retryFeedback": [],
  "dependencyContext": []
}
```

Response:
```json
{
  "type": "sql_ready|clarification|not_relevant",
  "conversationId": "session-123",
  "sql": "SELECT ...",
  "lightResponse": "One-sentence analyst summary.",
  "interpretationNotes": [],
  "caveats": [],
  "clarificationQuestion": "",
  "clarificationKind": "",
  "notRelevantReason": "",
  "rows": [],
  "rowCount": 0,
  "failedSql": null,
  "assumptions": []
}
```

Notes:
- `type=clarification` returns a non-empty `clarificationQuestion`.
- `type=not_relevant` explains the rejection in `notRelevantReason`.
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

Request:
```json
{
  "sql": "SELECT * FROM sales LIMIT 10",
  "warehouse": "optional",
  "database": "optional",
  "schema": "optional"
}
```

Response:
```json
{
  "rows": [],
  "rowCount": 0,
  "rewrittenSql": "SELECT * FROM sales LIMIT 10"
}
```

## Frontend API Routes

- `/api/chat` -> turn route proxy
- `/api/chat/stream` -> stream route proxy
- `/api/system-status` -> environment badge route returning `{"environment":"Sandbox|Production"}`

Both routes use orchestrator proxy mode (`WEB_BACKEND_MODE=orchestrator`, `ORCHESTRATOR_URL` set).
