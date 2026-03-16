# API Contracts

Use this file for request/response payload definitions, contract shapes, and boundary-level API expectations.

## Orchestrator Base

Default: `http://localhost:8787`

## POST `/v1/chat/turn`

Request:
```json
{
  "sessionId": "8d0c5c52-b0f2-4efe-91f9-1f8cd5ce3d8d",
  "message": "Show me spend by state last month, sorted descending.",
  "role": "analyst",
  "entitlementFilters": {
    "co_id": ["10001", "10002", "10003"]
  }
}
```

Request notes:
- `entitlementFilters.co_id` is the list of `CO_ID` values the caller is authorized to access for this turn.
- These are entitlement constraints, not user-selected analytic filters.
- The `co_id` dimension maps to `CO_ID` in the semantic model.
- `role` is optional request metadata accepted by the orchestrator contract.

Response:
```json
{
  "turnId": "0e2728b7-37c3-48cf-b696-6a8e62292151",
  "createdAt": "2026-03-16T14:00:00Z",
  "response": {
    "answer": "California, Texas, and Florida had the highest spend last month across the entitled CO_ID set.",
    "confidence": "high",
    "confidenceReason": "High confidence because the result is a direct ranking over a complete month window with no failed retrieval steps.",
    "whyItMatters": "The output identifies which states contributed the most spend within the entitled company scope for the requested month.",
    "presentationIntent": {
      "displayType": "chart",
      "chartType": "bar",
      "rationale": "A ranked state comparison is best shown as a bar chart.",
      "rankingObjectives": ["sorted_descending"]
    },
    "chartConfig": {
      "type": "bar",
      "x": "transaction_state",
      "y": "total_spend",
      "series": null,
      "xLabel": "State",
      "yLabel": "Spend",
      "yFormat": "currency"
    },
    "tableConfig": {
      "style": "ranked",
      "columns": [
        { "key": "transaction_state", "label": "State", "format": "string", "align": "left" },
        { "key": "total_spend", "label": "Spend", "format": "currency", "align": "right" },
        { "key": "data_from", "label": "Data From", "format": "date", "align": "left" },
        { "key": "data_through", "label": "Data Through", "format": "date", "align": "left" }
      ],
      "sortBy": "total_spend",
      "sortDir": "desc",
      "showRank": true
    },
    "metrics": [
      { "label": "Rows Retrieved", "value": 3, "delta": 0, "unit": "count" }
    ],
    "evidence": [],
    "insights": [
      {
        "id": "top_state_concentration",
        "title": "Spend is concentrated in a few states",
        "detail": "California, Texas, and Florida make up the top of the ranking for the February 2026 window.",
        "importance": "high"
      }
    ],
    "suggestedQuestions": [
      "Which merchants drove California spend last month?"
    ],
    "assumptions": [
      "Results are limited to CO_ID values 10001, 10002, and 10003."
    ],
    "trace": [
      {
        "id": "t1",
        "title": "Plan analysis",
        "summary": "Built a single-step ranking query for state spend in the requested month.",
        "status": "done",
        "runtimeMs": 42.5,
        "qualityChecks": ["plan_sanity"]
      },
      {
        "id": "t2",
        "title": "Retrieve data",
        "summary": "Queried state-level spend for entitled companies for 2026-02-01 through 2026-02-28.",
        "status": "done",
        "runtimeMs": 118.4,
        "sql": "SELECT transaction_state, SUM(spend) AS total_spend, MIN(resp_date) AS data_from, MAX(resp_date) AS data_through FROM cia_sales_insights_cortex WHERE co_id IN ('10001', '10002', '10003') AND resp_date >= DATE '2026-02-01' AND resp_date < DATE '2026-03-01' GROUP BY transaction_state ORDER BY total_spend DESC LIMIT 10"
      }
    ],
    "summaryCards": [
      { "label": "Top State", "value": "CA", "detail": "Highest spend in the February 2026 window" },
      { "label": "States Returned", "value": "3", "detail": "Top ranked rows in this example payload" }
    ],
    "primaryVisual": {
      "title": "Spend by State",
      "description": "State-level spend ranking for last month within the entitled CO_ID set.",
      "visualType": "ranking",
      "artifactKind": "ranking_breakdown"
    },
    "dataTables": [
      {
        "id": "spend_by_state_last_month",
        "name": "Spend by State",
        "columns": ["transaction_state", "total_spend", "data_from", "data_through"],
        "rows": [
          { "transaction_state": "CA", "total_spend": 1245032.44, "data_from": "2026-02-01", "data_through": "2026-02-28" },
          { "transaction_state": "TX", "total_spend": 1138874.21, "data_from": "2026-02-01", "data_through": "2026-02-28" },
          { "transaction_state": "FL", "total_spend": 978935.48, "data_from": "2026-02-01", "data_through": "2026-02-28" }
        ],
        "rowCount": 3,
        "description": "State-level spend totals for the February 2026 window used in the answer.",
        "sourceSql": "SELECT transaction_state, SUM(spend) AS total_spend, MIN(resp_date) AS data_from, MAX(resp_date) AS data_through FROM cia_sales_insights_cortex WHERE co_id IN ('10001', '10002', '10003') AND resp_date >= DATE '2026-02-01' AND resp_date < DATE '2026-03-01' GROUP BY transaction_state ORDER BY total_spend DESC LIMIT 10"
      }
    ],
    "artifacts": [],
    "facts": [],
    "comparisons": [],
    "evidenceStatus": "sufficient",
    "evidenceEmptyReason": "",
    "subtaskStatus": [],
    "claimSupport": [],
    "headline": "California led spend last month across the entitled CO_ID set.",
    "headlineEvidenceRefs": [],
    "periodStart": "2026-02-01",
    "periodEnd": "2026-02-28",
    "periodLabel": "Feb 1, 2026 to Feb 28, 2026"
  }
}
```

Response notes:
- `chartConfig` and `tableConfig` live under `response`, not at the top level.
- The `response` object above reflects the shared `AgentResponse` contract used by both the turn API and the final `response` event in the stream API.
- Clients should tolerate omitted optional fields where the shared contract marks them optional, even though the backend commonly emits empty arrays and default strings.
- On failure, the orchestrator route currently returns HTTP `400` with FastAPI's default error shape: `{"detail":"..."}`.

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

Stream notes:
- The final `response` event contains the same nested `AgentResponse` shape shown in `/v1/chat/turn.response`.
- The stream does not emit `turnId` or `createdAt`.

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
  "message": "Show me new vs repeat customer spend by month for the last 3 months.",
  "history": ["First show me total spend this month."],
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
  "sql": "SELECT DATE_TRUNC('MONTH', RESP_DATE) AS month, SUM(NEW_SPEND) AS new_spend, SUM(REPEAT_SPEND) AS repeat_spend FROM ...",
  "lightResponse": "Monthly new and repeat spend can be compared directly across the requested window.",
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

### GET `/api/v2/cortex/analyst/history/{conversation_id}`

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
  "sql": "SELECT TRANSACTION_STATE, SUM(SPEND) AS total_spend FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE LIMIT 10",
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
  "rewrittenSql": "SELECT transaction_state, SUM(spend) AS total_spend FROM cia_sales_insights_cortex GROUP BY transaction_state LIMIT 10"
}
```

## Frontend API Routes

- `/api/chat`
  - validates the same request schema as `/v1/chat/turn`
  - currently forwards only `sessionId` and `message` to the orchestrator
  - current implementation does not forward `role` or `entitlementFilters`
- `/api/chat/stream`
  - validates the same request schema as `/v1/chat/stream`
  - currently forwards only `sessionId` and `message` to the orchestrator
  - current implementation does not forward `role` or `entitlementFilters`
- `/api/system-status`
  - returns `{"environment":"Sandbox"}` or `{"environment":"Production"}`
  - falls back to `{"environment":"Sandbox"}` when the orchestrator is unavailable or the provider mode is unrecognized

The chat routes use orchestrator proxy mode (`WEB_BACKEND_MODE=orchestrator`, `ORCHESTRATOR_URL` set). `/api/system-status` queries orchestrator health when that configuration is present.
