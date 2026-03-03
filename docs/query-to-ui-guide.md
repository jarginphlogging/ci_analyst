# Query-to-UI Pipeline Guide

A detailed trace of how a user query travels through every layer of CI Analyst — from keystroke to rendered chart.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Stage 0: User Input (Browser)](#2-stage-0-user-input-browser)
3. [Stage 1: Next.js API Route (Proxy)](#3-stage-1-nextjs-api-route-proxy)
4. [Stage 2: FastAPI Endpoint](#4-stage-2-fastapi-endpoint)
5. [Stage 3: Orchestrator Pipeline](#5-stage-3-orchestrator-pipeline)
   - [T1: Planner](#t1-planner)
   - [T2: SQL Generation & Execution](#t2-sql-generation--execution)
   - [T3: Validation](#t3-validation)
   - [T4: Synthesis](#t4-synthesis)
6. [Stage 4: Streaming Back to the Browser](#6-stage-4-streaming-back-to-the-browser)
7. [Stage 5: UI Rendering](#7-stage-5-ui-rendering)
8. [Concrete End-to-End Example](#8-concrete-end-to-end-example)
9. [Error & Fallback Paths](#9-error--fallback-paths)

---

## 1. Architecture Overview

```
┌─────────────┐   POST /api/chat/stream   ┌──────────────────┐   POST /v1/chat/stream   ┌──────────────────────┐
│  Browser     │ ──────────────────────── │  Next.js Route   │ ────────────────────── │  FastAPI Orchestrator │
│  (React)     │ <── NDJSON stream ────── │  (Proxy)         │ <── NDJSON stream ──── │  (Python)             │
└─────────────┘                           └──────────────────┘                         └──────────────────────┘
                                                                                          │
                                                                                     ┌────┴────────────────┐
                                                                                     │  Pipeline Stages    │
                                                                                     │  T1 → T2 → T3 → T4 │
                                                                                     │  Plan  SQL  Val  Syn │
                                                                                     └─────────────────────┘
```

**Tech stack:**
- Frontend: Next.js 16 + React 19 + Tailwind CSS
- Backend: FastAPI + Pydantic
- LLM: Anthropic Claude / Azure OpenAI (configurable)
- SQL: Snowflake Cortex / SQLite sandbox
- Streaming: NDJSON over HTTP
- Charts: Custom SVG (no charting library)

---

## 2. Stage 0: User Input (Browser)

**File:** `apps/web/src/components/agent-workspace.tsx`

### What happens

The user types into a textarea and clicks Send (or presses Enter). Three starter prompts are offered when the conversation is empty:

- "Show me my sales in each state in descending order."
- "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?"
- "What are my top and bottom performing stores for 2025?..."

### Code flow

```
User types → textarea onChange → setInput(value)
User submits → form onSubmit → submitQuery(input)
```

**`submitQuery` (line 482)** does the following:

1. Trims the input, bails if empty or already loading
2. Creates a **user message** object and appends it to the `messages` array
3. Creates an empty **assistant message** with `isStreaming: true` and an empty `statusUpdates` array
4. Fires a `POST /api/chat/stream` request

### Output (HTTP request body)

```json
{
  "sessionId": "a1b2c3d4-...",
  "message": "What were my sales in each state in descending order?"
}
```

The `sessionId` is a UUID generated once per page load via `crypto.randomUUID()`.

### Schemas

The request body is validated by the shared Zod schema in `packages/contracts/src/index.ts`:

```typescript
const chatTurnRequestSchema = z.object({
  sessionId: z.string().uuid().optional(),
  message:   z.string().min(1),
  role:      z.string().optional(),
  explicitFilters: z.record(z.string(), z.array(z.string())).optional(),
});
```

---

## 3. Stage 1: Next.js API Route (Proxy)

**File:** `apps/web/src/app/api/chat/stream/route.ts`

### What happens

The Next.js route handler validates the request and decides whether to proxy to the real orchestrator or use mock data.

### Decision logic

```
if WEB_BACKEND_MODE === "orchestrator" && ORCHESTRATOR_URL is set:
    → Proxy to ${ORCHESTRATOR_URL}/v1/chat/stream
    → Pass through the NDJSON response stream
else:
    → Generate mock events via buildMockEvents(message)
    → Stream them with configurable delays
```

### Output

Returns a `Response` with headers:

```
Content-Type: application/x-ndjson; charset=utf-8
Cache-Control: no-cache, no-transform
Connection: keep-alive
```

The body is an NDJSON stream — one JSON object per line.

---

## 4. Stage 2: FastAPI Endpoint

**File:** `apps/orchestrator/app/main.py`

### What happens

The FastAPI server receives the request at `POST /v1/chat/stream`.

### Input (Pydantic model)

```python
class ChatTurnRequest(BaseModel):
    sessionId: Optional[UUID] = None
    message: str
    role: Optional[str] = None
    explicitFilters: Optional[dict[str, list[str]]] = None
```

### Processing

1. Request middleware generates/binds a unique `x-request-id`
2. Instantiates `ConversationalOrchestrator` (or reuses the singleton)
3. Calls `orchestrator.stream_events(request)` which returns an `AsyncIterator[str]`
4. Wraps in `StreamingResponse(media_type="application/x-ndjson")`

### Output

An async generator yielding NDJSON lines. Five event types:

| Event type     | When emitted | Shape |
|---------------|-------------|-------|
| `status`      | Each pipeline step starts | `{"type":"status","message":"Building governed plan"}` |
| `answer_delta`| Token-by-token answer streaming | `{"type":"answer_delta","delta":"Revenue grew"}` |
| `response`    | Draft and final response built | `{"type":"response","response":{...},"phase":"draft|final"}` |
| `error`       | Pipeline fails | `{"type":"error","message":"..."}` |
| `done`        | Stream complete | `{"type":"done"}` |

---

## 5. Stage 3: Orchestrator Pipeline

**File:** `apps/orchestrator/app/services/orchestrator.py`

The `stream_events` method (line ~292) launches a background worker that runs `_execute_pipeline`, then builds draft and final responses.

### Session context

Before the pipeline runs, the orchestrator extracts session history:

```python
def _session_context(self, request):
    session_id = str(request.sessionId or "anonymous")
    history = self._session_history.get(session_id, [])
    prior_history = history[-8:]      # last 8 messages for prompt context
    history.append(request.message)
    self._session_history[session_id] = history[-12:]  # retain last 12
    return session_id, prior_history
```

### Pipeline stages

```
_execute_pipeline() → (context, results, validation, stage_timings_ms)
    │
    ├── T1: create_plan()       → TurnExecutionContext
    ├── T2: run_sql()           → list[SqlExecutionResult]
    ├── T3: validate_results()  → ValidationResult
    └── T4: build_response()    → AgentResponse
```

---

### T1: Planner

**Files:**
- `apps/orchestrator/app/services/stages/planner_stage.py`
- `apps/orchestrator/app/prompts/markdown/planner_system.md`
- `apps/orchestrator/app/prompts/markdown/planner_user.md`

#### Input

| Field | Source | Example |
|-------|--------|---------|
| `user_message` | The raw user query | `"What were my sales in each state in descending order?"` |
| `history` | Last 6 conversation turns | `["Show me Q4 revenue", "Revenue in Q4 was $12.3M..."]` |
| `planner_scope_context` | Semantic model metadata | Tables, dimensions, metrics available |
| `max_steps` | Config (default 5) | `5` |

#### LLM System Prompt (planner_system.md)

```
You are the planner for Customer Insights analytics.

Your role is limited to relevance classification, bounded delegation
planning, and presentation intent selection.
Do not solve the analysis yourself and do not write SQL.

## Responsibilities
1. Classify query relevance as `in_domain`, `out_of_domain`, or `unclear`.
2. Build the minimum independent task plan for Snowflake Cortex Analyst
   sub-analysts.
3. Determine a presentation intent for the final response.
4. Mark `tooComplex=true` only when the minimum independent decomposition
   exceeds the provided max steps.

## Presentation Decision Tree
1. Single scalar → displayType="inline"
2. Time-series → displayType="chart", chartType="line"
3. Composition/breakdown → "chart"+"bar"/"stacked_bar" or "table"+"simple"
4. Ranking/top-N → "table"+"ranked"
5. Side-by-side comparison → "table"+"comparison"
6. Default → "table"+"simple"
```

#### LLM User Prompt (rendered)

```
Conversation history:
- Show me Q4 revenue
- Revenue in Q4 was $12.3M across all regions.

Planning scope:
[Tables: customer_facts, transaction_summary, store_dimension ...]
[Metrics: revenue, transaction_count, avg_sale_amount ...]
[Dimensions: state, region, store_name, customer_segment ...]

Max steps: 5
Question: What were my sales in each state in descending order?

Populate these structured fields:
- `relevance`: `in_domain|out_of_domain|unclear`
- `relevanceReason`: short string
- `presentationIntent`: `{displayType, chartType, tableStyle, rationale}`
- `tooComplex`: true only when minimum decomposition exceeds max steps
- `tasks`: array of task objects
```

#### LLM Output (structured JSON)

```json
{
  "relevance": "in_domain",
  "relevanceReason": "Sales by state is directly answerable from the semantic model.",
  "presentationIntent": {
    "displayType": "table",
    "chartType": null,
    "tableStyle": "ranked",
    "rationale": "Descending order implies a ranked table of states by sales."
  },
  "tooComplex": false,
  "tasks": [
    {
      "task": "Retrieve total sales for each state, ordered descending by sales amount.",
      "dependsOn": [],
      "independent": true
    }
  ]
}
```

#### Inline checks applied

- **`check_plan_sanity`**: Verifies step count <= 5, no duplicates, valid structure
- If plan is empty → inserts a fallback single-step plan
- If plan fails sanity checks → `PlannerBlockedError` (pipeline aborts)

#### Output

A `TurnExecutionContext`:

```python
TurnExecutionContext(
    route="standard",
    plan=[
        QueryPlanStep(
            id="step_1",
            goal="Retrieve total sales for each state, ordered descending by sales amount.",
            dependsOn=[],
            independent=True,
        )
    ],
    presentation_intent=PresentationIntent(
        displayType="table",
        chartType=None,
        tableStyle="ranked",
        rationale="Descending order implies a ranked table...",
    ),
    sql_assumptions=[],
    sql_retry_feedback=[],
)
```

---

### T2: SQL Generation & Execution

**Files:**
- `apps/orchestrator/app/services/stages/sql_stage.py`
- `apps/orchestrator/app/services/stages/sql_stage_generation.py`
- `apps/orchestrator/app/prompts/markdown/sql_system.md`
- `apps/orchestrator/app/prompts/markdown/sql_user.md`

This runs **once per plan step**, respecting dependency order. Steps marked `independent=true` can run in parallel.

#### Input (per step)

| Field | Source | Example |
|-------|--------|---------|
| `user_message` | Original query | `"What were my sales in each state..."` |
| `step_id` | From plan | `"step_1"` |
| `step_goal` | From plan | `"Retrieve total sales for each state..."` |
| `semantic_model_summary` | Rendered model schema | Tables, columns, joins, policy |
| `history` | Last 6 turns | Conversation context |
| `prior_sql` | SQL from earlier steps (this turn) | `[]` (first step) |
| `retry_feedback` | Failed prior attempts | `[]` (first try) |
| `route` | Execution mode | `"standard"` |

#### LLM System Prompt (sql_system.md)

```
You are a SQL generator sub-analyst for governed customer insights data.

You must produce one of three outcomes:
- `sql_ready`: provide one read-only Snowflake SQL query.
- `clarification`: provide a precise clarification question.
- `not_relevant`: explain why the request is out of scope.

Rules:
- Never generate mutating SQL.
- Keep SQL aligned to the provided semantic model and constraints.
- Use retry feedback to avoid repeating prior failures.
```

#### LLM User Prompt (rendered)

```
Conversation history:
- Show me Q4 revenue
- Revenue in Q4 was $12.3M across all regions.

Semantic model summary:
  Table: TRANSACTION_SUMMARY
    Columns: STATE (string), REVENUE (number), TRANSACTION_COUNT (number),
             SALE_DATE (date), STORE_ID (string), CUSTOMER_SEGMENT (string)
    Metrics: revenue = SUM(REVENUE), transaction_count = SUM(TRANSACTION_COUNT)
  [... additional tables ...]
  Policy: restrictedColumns=[SSN, DOB], defaultRowLimit=1000

Question: What were my sales in each state in descending order?
Step id: step_1
Step goal: Retrieve total sales for each state, ordered descending by sales amount.
Route: standard

Prior SQL in this turn:
- none

Retry feedback from prior attempts:
- none

Populate these structured fields:
- `generationType`: `sql_ready|clarification|not_relevant`
- `sql`: string (required when generationType=sql_ready)
- `rationale`: short string
- `assumptions`: array of strings
```

#### LLM Output (structured JSON)

```json
{
  "generationType": "sql_ready",
  "sql": "SELECT STATE, SUM(REVENUE) AS TOTAL_SALES FROM TRANSACTION_SUMMARY GROUP BY STATE ORDER BY TOTAL_SALES DESC LIMIT 1000",
  "rationale": "Aggregates revenue by state and sorts descending as requested.",
  "assumptions": [
    "Using REVENUE column as the sales measure.",
    "Applied default row limit of 1000."
  ]
}
```

#### Post-LLM processing

1. **SQL guardrails** (`sql_guardrails.py`): Checks for restricted columns (SSN, DOB), mutating statements, etc.
2. **SQL execution**: Runs against the configured provider (Snowflake / SQLite sandbox)
3. **Row normalization**: Standardizes data types across result columns
4. **Retry loop**: If generation or execution fails, retries up to 3 times with feedback

#### Inline checks applied

- **`check_sql_syntax`**: Basic pattern validation
- **`check_result_sanity`**: Rows exist, <= 10K rows, valid structure

#### Output

```python
[
    SqlExecutionResult(
        sql="SELECT STATE, SUM(REVENUE) AS TOTAL_SALES FROM TRANSACTION_SUMMARY GROUP BY STATE ORDER BY TOTAL_SALES DESC LIMIT 1000",
        rows=[
            {"STATE": "California", "TOTAL_SALES": 4523100.50},
            {"STATE": "Texas",      "TOTAL_SALES": 3891200.25},
            {"STATE": "New York",   "TOTAL_SALES": 3102400.75},
            # ... more rows
        ],
        rowCount=48,
    )
]
```

---

### T3: Validation

**File:** `apps/orchestrator/app/services/stages/validation_stage.py`

#### Input

The list of `SqlExecutionResult` from T2.

#### Checks performed

| Check | Condition | Pass if |
|-------|-----------|---------|
| Has results | `len(results) > 0` | At least one result set |
| Has rows | `sum(r.rowCount) > 0` | Total rows > 0 |
| Row limit | Per-step row count | <= policy max (5000) |
| Null rate | Sample first N rows | < 95% null values |

#### Inline check

- **`check_validation_contract`**: Confirms `passed=true` and checks list is non-empty

#### Output

```python
ValidationResult(
    passed=True,
    checks=["has_results: pass", "has_rows: pass (48 total)", "row_limit: pass"]
)
```

If validation fails → `RuntimeError` (pipeline aborts, error event emitted).

---

### T4: Synthesis

**Files:**
- `apps/orchestrator/app/services/stages/synthesis_stage.py`
- `apps/orchestrator/app/services/stages/data_summarizer_stage.py`
- `apps/orchestrator/app/services/table_analysis.py`
- `apps/orchestrator/app/prompts/markdown/synthesis_system.md`
- `apps/orchestrator/app/prompts/markdown/synthesis_user.md`

Synthesis runs **twice**: once for the fast draft (deterministic, no LLM) and once for the final (LLM-powered).

#### Pre-synthesis data transforms

Before the LLM call, the orchestrator builds several derived structures from the raw SQL results:

1. **DataTables** — wraps each `SqlExecutionResult` into a named table:
   ```python
   DataTable(
       id="table_1",
       name="Sales by State",
       columns=["STATE", "TOTAL_SALES"],
       rows=[{"STATE": "California", "TOTAL_SALES": 4523100.50}, ...],
       rowCount=48,
       sourceSql="SELECT STATE, SUM(REVENUE)..."
   )
   ```

2. **Analysis Artifacts** — structured breakdowns detected from the data shape:
   ```python
   AnalysisArtifact(
       id="artifact_1",
       kind="ranking_breakdown",
       title="Sales by State (Ranked)",
       columns=["STATE", "TOTAL_SALES"],
       rows=[...],
       dimensionKey="STATE",
       valueKey="TOTAL_SALES",
   )
   ```

3. **Table summaries** — compact statistical summaries of each table (column types, min/max, distinct counts) used as LLM input instead of raw rows.

4. **Evidence summary** — extracted metrics and dimensions for the LLM context.

#### Draft response (deterministic, no LLM)

Built from `_deterministic_answer_fallback` and the data structures above. Emitted as `phase="draft"` so the UI has something to show immediately.

```json
{
  "type": "response",
  "phase": "draft",
  "response": {
    "answer": "Total Sales: $45,231,005 | 48 states returned",
    "confidence": "medium",
    "dataTables": [...],
    "artifacts": [...],
    "trace": [...]
  }
}
```

#### Final response — LLM Synthesis

##### System Prompt (synthesis_system.md)

```
You are an executive analytics narrator for a governed customer-insights
platform.

## Responsibilities
1. Write a concise analytical answer grounded in supplied summaries.
2. Write a concise `whyItMatters` statement.
3. Emit valid `chartConfig` or `tableConfig` aligned with presentation
   intent and available columns.
4. Emit confidence, summary cards, insights, assumptions, follow-up questions.

## Narrative Guardrails
- Do not fabricate numbers.
- Do not speculate about causes unsupported by provided summaries.
- Lead with the headline finding.
- Use specific numbers where available.

## Visual Rules
- Prefer `chartConfig` when meaningful and reliable.
- Prefer `tableConfig` when a table is more readable.
- If chart reliability is weak, set `chartConfig=null` and provide `tableConfig`.
```

##### User Prompt (rendered)

```
Conversation history:
- Show me Q4 revenue
- Revenue in Q4 was $12.3M across all regions.

Question: What were my sales in each state in descending order?
Route: standard
Presentation intent: {"displayType":"table","tableStyle":"ranked","rationale":"Descending order implies a ranked table..."}

Synthesis context package:
{
  "queryContext": {"originalUserQuery": "What were my sales in each state...", "route": "standard"},
  "plan": [{"id": "step_1", "goal": "Retrieve total sales for each state..."}],
  "executedSteps": [{
    "stepIndex": 1,
    "planStep": {"id": "step_1", "goal": "..."},
    "executedSql": "SELECT STATE, SUM(REVENUE)...",
    "rowCount": 48,
    "tableSummary": {
      "columns": {"STATE": {"type": "string", "distinct": 48}, "TOTAL_SALES": {"type": "number", "min": 102400, "max": 4523100}}
    }
  }],
  "portfolioSummary": {"tableCount": 1, "totalRows": 48}
}

Evidence summary:
Dimensions: STATE (48 distinct values)
Metrics: TOTAL_SALES (min=102,400, max=4,523,100, mean=942,312)

Populate these structured fields:
- `answer`: concise direct answer
- `whyItMatters`: concise impact statement
- `confidence`: high|medium|low
- `summaryCards`: array of 1-3 objects {label, value, detail}
- `chartConfig`: object or null
- `tableConfig`: object or null
- `insights`: array of up to 4 objects
- `suggestedQuestions`: array of exactly 3 strings
- `assumptions`: array of up to 5 strings
```

##### LLM Output (structured JSON)

```json
{
  "answer": "California leads all states with $4.5M in total sales, followed by Texas ($3.9M) and New York ($3.1M). The top 5 states account for 42% of total revenue across 48 states.",
  "whyItMatters": "Geographic concentration in a few states creates revenue risk — understanding state-level performance helps prioritize regional investment and marketing allocation.",
  "confidence": "high",
  "confidenceReason": "Direct aggregation from complete transaction data with no joins or assumptions needed.",
  "summaryCards": [
    {"label": "Top State", "value": "California — $4.5M", "detail": "18.6% of total"},
    {"label": "States Returned", "value": "48", "detail": "All active states"},
    {"label": "Total Sales", "value": "$45.2M", "detail": "Across all states"}
  ],
  "chartConfig": null,
  "tableConfig": {
    "style": "ranked",
    "columns": [
      {"key": "STATE", "label": "State", "format": "string", "align": "left"},
      {"key": "TOTAL_SALES", "label": "Total Sales", "format": "currency", "align": "right"}
    ],
    "sortBy": "TOTAL_SALES",
    "sortDir": "desc",
    "showRank": true
  },
  "insights": [
    {"title": "Top 5 concentration", "detail": "CA, TX, NY, FL, and IL account for 42% of total revenue.", "importance": "high"},
    {"title": "Long tail", "detail": "The bottom 20 states contribute only 8% of total sales.", "importance": "medium"}
  ],
  "suggestedQuestions": [
    "How do sales in the top 5 states compare to last year?",
    "What is the average transaction size by state?",
    "Which states have the highest growth rate?"
  ],
  "assumptions": [
    "Using REVENUE as the sales measure.",
    "All time periods included (no date filter applied).",
    "Default row limit of 1000 applied."
  ]
}
```

#### Post-synthesis inline checks

- **`check_answer_sanity`**: Non-empty, not an error pattern, minimum length
  - If answer looks like an error → replaced with deterministic fallback
- **`check_pii`**: Scans for email, phone, SSN patterns
  - If PII detected → `redact_pii()` strips it from the answer

#### Final output

A complete `AgentResponse` combining the LLM synthesis with the deterministic data:

```python
AgentResponse(
    answer="California leads all states with $4.5M...",
    confidence="high",
    confidenceReason="Direct aggregation from complete transaction data...",
    whyItMatters="Geographic concentration in a few states...",
    presentationIntent=PresentationIntent(displayType="table", tableStyle="ranked", ...),
    chartConfig=None,
    tableConfig=TableConfig(style="ranked", columns=[...], sortBy="TOTAL_SALES", sortDir="desc", showRank=True),
    metrics=[...],
    evidence=[...],
    insights=[Insight(title="Top 5 concentration", ...), ...],
    suggestedQuestions=["How do sales in the top 5 states compare to last year?", ...],
    assumptions=["Using REVENUE as the sales measure.", ...],
    trace=[TraceStep(id="t1", ...), TraceStep(id="t2", ...), ...],
    summaryCards=[SummaryCard(label="Top State", value="California — $4.5M", ...), ...],
    primaryVisual=PrimaryVisual(title="Sales by State", visualType="ranking"),
    dataTables=[DataTable(id="table_1", columns=["STATE","TOTAL_SALES"], rows=[...], ...)],
    artifacts=[AnalysisArtifact(kind="ranking_breakdown", ...)],
)
```

---

## 6. Stage 4: Streaming Back to the Browser

**File:** `apps/orchestrator/app/services/orchestrator.py` → `stream_events()`

The orchestrator emits events in this sequence:

```
1. {"type":"status","message":"Building governed plan"}
2. {"type":"status","message":"Building plan..."}           ← heartbeat
3. {"type":"status","message":"Plan ready with 1 step(s)"}
4. {"type":"status","message":"Executing SQL and retrieving result tables"}
5. {"type":"status","message":"Executing governed SQL..."}  ← heartbeat
6. {"type":"status","message":"Running numeric QA and consistency checks"}
7. {"type":"response","response":{...},"phase":"draft"}
8. {"type":"answer_delta","delta":"California "}
9. {"type":"answer_delta","delta":"leads "}
10. {"type":"answer_delta","delta":"all "}
    ... (token-by-token deltas)
11. {"type":"status","message":"Finalizing response payload and audit trace"}
12. {"type":"response","response":{...},"phase":"final"}
13. {"type":"done"}
```

**Answer deltas** are computed by `build_incremental_answer_deltas()` — it diffs the draft answer and the final answer, then yields word-by-word tokens so the UI can animate typing.

The Next.js route (`apps/web/src/app/api/chat/stream/route.ts`) proxies this stream byte-for-byte to the browser.

---

## 7. Stage 5: UI Rendering

**File:** `apps/web/src/components/agent-workspace.tsx`

### Stream event handling (line 522)

The browser reads the NDJSON stream via `readNdjsonStream()` from `apps/web/src/lib/stream.ts`. Each event type updates React state:

| Event | State update |
|-------|-------------|
| `status` | Append to `message.statusUpdates[]` → spinner shows latest |
| `answer_delta` | Concatenate to `message.text` → typing animation |
| `response` (draft) | Store as `message.draftResponse` → show immediate results |
| `response` (final) | Store as `message.response`, clear draft → final render |
| `error` | Set `message.text` to error, stop streaming |
| `done` | Set `isStreaming = false` → hide spinner |

### Component rendering hierarchy

Once the final `response` lands, the assistant message renders these sections in order:

```
Assistant Message
├── Status Indicator (while streaming)
│   └── Animated spinner + last status text
│
├── Failure State (if any trace step has status="blocked")
│   └── Rose-colored alert + AnalysisTrace
│
├── Success State
│   ├── Why It Matters                    ← response.whyItMatters
│   │   └── Italic text block
│   │
│   ├── Summary Cards                     ← response.summaryCards[]
│   │   └── Grid of {label, value, detail} cards
│   │
│   ├── EvidenceTable                     ← response.chartConfig + response.tableConfig + response.dataTables
│   │   ├── ChartPanel (if chartConfig valid)
│   │   │   ├── AreaChart (line/stacked_bar) — custom SVG
│   │   │   └── BarChart (bar/grouped_bar) — custom SVG
│   │   └── TablePanel (if chartConfig null or invalid)
│   │       └── Ranked/simple/comparison table with formatted cells
│   │
│   ├── Priority Insights                 ← response.insights[] (top 3, sorted by importance)
│   │   └── Cards with title + detail
│   │
│   ├── DataExplorer                      ← response.dataTables[]
│   │   └── Expandable section with raw data, CSV/JSON export, SQL source
│   │
│   ├── AnalysisTrace                     ← response.trace[]
│   │   └── Collapsible steps: T1→T2→T3→T4 with prompts, outputs, checks
│   │
│   ├── Assumptions                       ← response.assumptions[]
│   │   └── Bulleted list
│   │
│   └── Suggested Next Questions          ← response.suggestedQuestions[]
│       └── Clickable buttons → re-submit as new query
```

### EvidenceTable decision logic

**File:** `apps/web/src/components/evidence-table.tsx`

```
Has dataTables?
  ├── No  → "No tabular output" message
  └── Yes → Has chartConfig?
             ├── No  → Render TablePanel
             └── Yes → checkReadiness(chartConfig, table)
                        ├── Ready → Render ChartPanel
                        └── Not ready → Fallback to TablePanel
```

**Chart readiness checks:**
- X-axis column must exist in the table
- Y-axis column(s) must exist in the table
- Minimum 2 distinct X values
- Line charts need >= 3 X data points
- Max 10 series categories
- At least 2 numeric data points

### Chart rendering

Charts use **custom SVG** (no Recharts/D3/etc):

- `chartSeriesFromTable()` extracts X/Y data from the DataTable
- Linear scales computed from data min/max with 8% padding
- Colors: `["#0284c7", "#ea580c", "#059669", "#dc2626", "#4338ca", "#0f766e"]`
- Y-axis formatting: `currency` (with M/B abbreviations), `percent`, `number`
- X-axis: dates formatted as "Mon DD" with conditional year

### Table rendering

TablePanel renders data with:
- Columns from `tableConfig.columns[]` — each with `key`, `label`, `format`, `align`
- Optional rank column when `showRank=true`
- Sorting by `sortBy`/`sortDir`
- Cell formatting per format type (currency, number, percent, date, string)

---

## 8. Concrete End-to-End Example

**User query:** `"What were my sales in each state in descending order?"`

### Step-by-step trace

| # | Layer | What happens | Key data |
|---|-------|-------------|----------|
| 1 | Browser | User types and submits | `{sessionId: "abc-123", message: "What were my sales in each state in descending order?"}` |
| 2 | Next.js route | Validates, proxies to orchestrator | `POST ${ORCHESTRATOR_URL}/v1/chat/stream` |
| 3 | FastAPI | Receives request, extracts session history | `prior_history = ["Show me Q4 revenue"]` |
| 4 | T1 Planner | LLM classifies as `in_domain`, creates 1-step plan | `plan=[{goal: "Retrieve total sales per state, descending"}]`, `presentationIntent={table, ranked}` |
| 5 | T1 Checks | `check_plan_sanity` → pass (1 step <= 5) | Status: `"Plan ready with 1 step(s)"` |
| 6 | T2 SQL Gen | LLM generates SQL from semantic model + step goal | `SELECT STATE, SUM(REVENUE) AS TOTAL_SALES FROM TRANSACTION_SUMMARY GROUP BY STATE ORDER BY TOTAL_SALES DESC` |
| 7 | T2 SQL Exec | SQL runs against Snowflake/SQLite | 48 rows returned |
| 8 | T2 Checks | `check_sql_syntax` → pass, `check_result_sanity` → pass | 48 rows, valid structure |
| 9 | T3 Validation | Row counts, null rates checked | `{passed: true}` |
| 10 | T4 Draft | Deterministic summary built from raw data | `"Total Sales: $45.2M \| 48 states"` → emitted as `phase="draft"` |
| 11 | T4 Final | LLM synthesizes narrative, picks `tableConfig` | Full answer with insights, assumptions, suggested questions |
| 12 | T4 Checks | `check_answer_sanity` → pass, `check_pii` → pass | Answer is clean |
| 13 | Stream | Events emitted: status × N → draft → deltas → final → done | 13+ NDJSON lines |
| 14 | Browser | Events parsed, state updated progressively | Spinner → draft table → typing animation → final render |
| 15 | UI | Renders: Why It Matters → Summary Cards → Ranked Table → Insights → Suggested Questions | Full interactive response |

### What the user sees (in order)

1. Their question appears as a right-aligned chat bubble
2. Animated spinner with status: "Building governed plan" → "Executing SQL..." → etc.
3. Draft table appears with basic data (from `phase="draft"`)
4. Answer text types in word-by-word
5. Final response replaces draft: polished narrative, formatted ranked table, insights, suggested questions
6. Spinner disappears, suggested questions become clickable

---

## 9. Error & Fallback Paths

### Planner blocked (out of domain)

```
T1 → PlannerBlockedError(stop_reason="out_of_domain")
   → Guidance response with low confidence
   → UI shows blocked trace step with reason
```

### SQL generation failed

```
T2 → SqlGenerationBlockedError (after 3 retries)
   → Clarification response with SQL error context
   → UI shows blocked trace with failed SQL and error details
```

### Validation failed

```
T3 → RuntimeError("Result validation failed.")
   → Generic failure message
   → UI shows error state
```

### Answer sanity check fails

```
T4 → check_answer_sanity returns fail
   → Answer replaced with deterministic fallback
   → Assumption added: "Inline check fallback applied: ..."
   → UI renders fallback answer (still shows tables/data)
```

### PII detected

```
T4 → check_pii returns fail
   → redact_pii() strips sensitive patterns
   → Assumption added: "Inline check redaction applied: ..."
   → UI renders redacted answer
```

### Network/stream failure

```
Browser → fetch fails or stream breaks
   → Catch block sets: "I could not process that request. Please retry."
   → isStreaming=false, loading=false
```
