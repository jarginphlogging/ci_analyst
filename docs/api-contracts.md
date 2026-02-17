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
  "timestamp": "..."
}
```

## Frontend API Routes

- `/api/chat` -> turn route (proxy/fallback)
- `/api/chat/stream` -> stream route (proxy/fallback)

Both routes support:
- local mock mode (`WEB_USE_LOCAL_MOCK=true`)
- orchestrator proxy mode (`WEB_USE_LOCAL_MOCK=false`, `ORCHESTRATOR_URL` set)
