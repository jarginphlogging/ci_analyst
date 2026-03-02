# Pipeline Walkthrough: Query → Visual Response

**User query:** *“What were my sales by month for the last year split by new and repeat customers?”*

-----

## 1. Planner Agent

### System Prompt

```
You are the Planner for a conversational analytics system in a corporate
banking environment. You receive a user's natural language question and
produce a structured execution plan.

## Your Responsibilities

1. Classify the query complexity tier (simple, moderate, complex)
2. Decompose into subtasks if needed (moderate/complex only)
3. Classify the turn type if conversation history is present
4. Determine the presentation intent for the final response

## Complexity Tiers

- SIMPLE: Single data retrieval, single aggregation, one answer.
  "What was total revenue last quarter?" "How many active accounts?"
- MODERATE: Multiple related data points, comparative analysis, or
  dimensional breakdowns requiring narrative synthesis.
  "Compare revenue by region QoQ" "Sales by month split by customer type"
- COMPLEX: Requires iterative reasoning, root cause analysis, or
  pattern identification across multiple queries.
  "Why did Northeast revenue decline while others grew?"

## Subtask Decomposition Rules

SINGLE SUBTASK when:
- The question can be answered by one query, even if the query is complex
- Comparisons across time periods (these are WHERE/GROUP BY problems,
  not separate queries)
- Comparisons across segments or categories (same — one query, grouped)
- Breakdowns, rankings, trends, aggregations of any complexity

MULTIPLE SUBTASKS only when:
- The question requires fundamentally different measures that cannot
  reasonably be combined in a single query
- Example: "Why did revenue decline?" might need revenue trends,
  customer counts, and average transaction values — three different
  measures with different aggregation logic
- Each subtask should be independently meaningful and answer a
  distinct analytical sub-question

The first subtask should always be the one that most directly answers
the user's question. Subsequent subtasks provide supporting context.
Only the first subtask's result set will be visualized.

If in doubt, use a single subtask. Cortex Analyst can handle complex
queries. Decomposition adds latency and complexity — only use it when
a single query genuinely cannot answer the question.

## Turn Classification (only when conversation history is present)

- NEW: No dependency on prior turns.
- REFINE: User wants to adjust the previous query (different filter,
  added dimension, narrower scope).
- FOLLOWUP: New question that references or builds on prior results.

## Presentation Intent

Classify the expected output using this decision tree. Work top to
bottom, stop at the first match.

1. Will the answer be a single scalar value (one number, one name,
   one date, yes/no)?
   → display_type: "inline"

2. Does the query involve values across a TIME dimension (days, weeks,
   months, quarters, years)?

   2a. One measure tracked over time?
       → display_type: "chart", chart_type: "line"

   2b. Multiple categories tracked over the same time dimension?
       → display_type: "chart", chart_type: "line"

   2c. Period-over-period deltas or growth rates specifically?
       → display_type: "chart", chart_type: "grouped_bar"

3. Does the query ask about composition or breakdown of a whole?

   3a. Fewer than ~8 expected categories?
       → display_type: "chart", chart_type: "bar" or "stacked_bar"

   3b. Many expected categories (8+)?
       → display_type: "table", table_style: "simple"

4. Ranking, top-N, or bottom-N?
   → display_type: "table", table_style: "ranked"

5. Comparison of specific named entities side by side?
   → display_type: "table", table_style: "comparison"

6. Filtered list of records?
   → display_type: "table", table_style: "simple"

7. Default fallback:
   - Expected rows <= 3 → display_type: "inline"
   - Expected rows 4-50 → display_type: "table", table_style: "simple"
   - Expected rows 50+ → display_type: "table", table_style: "simple"

Include a short "rationale" string explaining your classification.
This is for debugging only and will not be shown to the user.

## Output Schema

Respond with valid JSON matching this exact structure:

{
  "complexity_tier": "simple" | "moderate" | "complex",
  "turn_type": "new" | "refine" | "followup",
  "intent": "<1-2 sentence natural language description of what the user wants>",
  "subtasks": [
    {
      "id": "st_1",
      "question": "<natural language question for Cortex Analyst>",
      "depends_on": []
    }
  ],
  "presentation_intent": {
    "display_type": "inline" | "table" | "chart",
    "chart_type": "line" | "bar" | "stacked_bar" | "grouped_bar" | null,
    "table_style": "simple" | "ranked" | "comparison" | null,
    "rationale": "<why this display type>"
  }
}
```

### Planner Input

```json
{
  "current_message": "What were my sales by month for the last year split by new and repeat customers?",
  "recent_turns": [],
  "semantic_model_summary": "Tables: orders (order_date, amount, customer_type, region, product_line). Metrics: total_sales = SUM(amount). Dimensions: customer_type (New, Repeat), region, product_line. Time grain: order_date supports daily/weekly/monthly/quarterly/yearly."
}
```

### Planner Output

```json
{
  "complexity_tier": "simple",
  "turn_type": "new",
  "intent": "Monthly sales totals for the trailing 12 months, broken down by customer type (new vs repeat)",
  "subtasks": [
    {
      "id": "st_1",
      "question": "What were total sales by month for the last 12 months, split by new and repeat customer type?",
      "depends_on": []
    }
  ],
  "presentation_intent": {
    "display_type": "chart",
    "chart_type": "line",
    "rationale": "Time series (monthly) with a categorical split (customer_type) — matches rule 2b"
  }
}
```

> **Note:** This is classified as `simple` because it’s a single query, even
> though the presentation is a chart. Complexity tier drives the execution
> path (how many SQL calls, what synthesis depth). Presentation intent drives
> the output format. They’re independent dimensions.

-----

## 2. Executor (SQL Sub-Agent)

The executor receives each subtask’s `question` field and passes it to
Cortex Analyst, which generates and executes SQL against the semantic model.

### What Cortex Analyst Sees

```
What were total sales by month for the last 12 months, split by new
and repeat customer type?
```

### Generated SQL (by Cortex Analyst)

```sql
SELECT
    DATE_TRUNC('month', order_date) AS month,
    customer_type,
    SUM(amount) AS total_sales
FROM orders
WHERE order_date >= DATEADD('year', -1, CURRENT_DATE())
GROUP BY DATE_TRUNC('month', order_date), customer_type
ORDER BY month, customer_type
```

### Validation (deterministic, every query)

```python
# This runs on every query, no exceptions. < 100ms.

def validate_sql(sql: str, semantic_model: SemanticModel) -> ValidationResult:
    """
    Four-stage deterministic validation.
    Returns ValidationResult with pass/fail and error details.
    """

    # 1. Syntax — does it parse?
    try:
        parsed = sqlglot.parse_one(sql, dialect="snowflake")
    except SqlglotError as e:
        return ValidationResult(passed=False, stage="syntax", error=str(e))

    # 2. Safety — no writes, no DDL, no system tables
    blocked_patterns = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
                        "ALTER", "GRANT", "REVOKE", "COPY", "PUT"]
    for token in parsed.walk():
        if token.key.upper() in blocked_patterns:
            return ValidationResult(
                passed=False, stage="safety",
                error=f"Blocked operation: {token.key}"
            )

    # 3. Schema — all referenced tables/columns exist in semantic model
    referenced_tables = extract_tables(parsed)
    referenced_columns = extract_columns(parsed)
    for table in referenced_tables:
        if table not in semantic_model.tables:
            return ValidationResult(
                passed=False, stage="schema",
                error=f"Unknown table: {table}"
            )
    for col in referenced_columns:
        if not semantic_model.has_column(col.table, col.name):
            return ValidationResult(
                passed=False, stage="schema",
                error=f"Unknown column: {col}"
            )

    # 4. Sanity — row limit, no cartesian joins, reasonable complexity
    if not has_limit_or_aggregation(parsed):
        # Add a safety LIMIT to prevent runaway queries
        sql = f"SELECT * FROM ({sql}) LIMIT 10000"

    return ValidationResult(passed=True, sql=sql)
```

### SQL Result Set

```json
{
  "subtask_id": "st_1",
  "sql": "SELECT DATE_TRUNC('month', order_date) AS month, ...",
  "columns": [
    { "name": "month", "type": "date" },
    { "name": "customer_type", "type": "string" },
    { "name": "total_sales", "type": "number" }
  ],
  "rows": [
    { "month": "2025-03-01", "customer_type": "New",    "total_sales": 142000 },
    { "month": "2025-03-01", "customer_type": "Repeat", "total_sales": 318000 },
    { "month": "2025-04-01", "customer_type": "New",    "total_sales": 156000 },
    { "month": "2025-04-01", "customer_type": "Repeat", "total_sales": 335000 },
    { "month": "2025-05-01", "customer_type": "New",    "total_sales": 139000 },
    { "month": "2025-05-01", "customer_type": "Repeat", "total_sales": 341000 },
    { "month": "2025-06-01", "customer_type": "New",    "total_sales": 161000 },
    { "month": "2025-06-01", "customer_type": "Repeat", "total_sales": 329000 },
    { "month": "2025-07-01", "customer_type": "New",    "total_sales": 182000 },
    { "month": "2025-07-01", "customer_type": "Repeat", "total_sales": 344000 },
    { "month": "2025-08-01", "customer_type": "New",    "total_sales": 175000 },
    { "month": "2025-08-01", "customer_type": "Repeat", "total_sales": 352000 },
    { "month": "2025-09-01", "customer_type": "New",    "total_sales": 168000 },
    { "month": "2025-09-01", "customer_type": "Repeat", "total_sales": 348000 },
    { "month": "2025-10-01", "customer_type": "New",    "total_sales": 151000 },
    { "month": "2025-10-01", "customer_type": "Repeat", "total_sales": 339000 },
    { "month": "2025-11-01", "customer_type": "New",    "total_sales": 133000 },
    { "month": "2025-11-01", "customer_type": "Repeat", "total_sales": 326000 },
    { "month": "2025-12-01", "customer_type": "New",    "total_sales": 128000 },
    { "month": "2025-12-01", "customer_type": "Repeat", "total_sales": 315000 },
    { "month": "2026-01-01", "customer_type": "New",    "total_sales": 137000 },
    { "month": "2026-01-01", "customer_type": "Repeat", "total_sales": 322000 },
    { "month": "2026-02-01", "customer_type": "New",    "total_sales": 145000 },
    { "month": "2026-02-01", "customer_type": "Repeat", "total_sales": 331000 }
  ],
  "row_count": 24,
  "execution_time_ms": 1230
}
```

-----

## 3. Building the Data Summary (deterministic, no LLM)

The full result set is NEVER sent to the synthesizer’s context window.
Instead, a deterministic Python function pre-computes a compact summary
that gives the LLM everything it needs to write a great narrative while
keeping context size predictable regardless of result set size.

```python
def build_data_summary(
    result: SQLResult,
    presentation_intent: PresentationIntent,
) -> dict:
    df = pd.DataFrame(result.rows)

    summary = {
        "row_count": len(df),
        "columns": [
            {"name": c["name"], "type": c["type"]}
            for c in result.columns
        ],
        "sample_rows": {
            "first_5": df.head(5).to_dict(orient="records"),
            "last_5": df.tail(5).to_dict(orient="records"),
        },
    }

    # Pre-compute stats the LLM would otherwise have to eyeball
    for col in result.columns:
        if col["type"] == "number":
            series = df[col["name"]]
            summary[f"{col['name']}_stats"] = {
                "sum": round(series.sum(), 2),
                "mean": round(series.mean(), 2),
                "min": round(series.min(), 2),
                "max": round(series.max(), 2),
                "median": round(series.median(), 2),
            }
        elif col["type"] == "string":
            summary[f"{col['name']}_values"] = (
                df[col["name"]].unique().tolist()
            )

    # Per-series summaries for time + category splits
    if presentation_intent.chart_type == "line":
        time_col = next(
            c["name"] for c in result.columns if c["type"] == "date"
        )
        series_col = next(
            (c["name"] for c in result.columns if c["type"] == "string"),
            None,
        )
        measure_col = next(
            c["name"] for c in result.columns if c["type"] == "number"
        )
        if series_col:
            grouped = df.groupby(series_col)
            summary["series_summary"] = {
                name: {
                    "total": round(group[measure_col].sum(), 2),
                    "mean": round(group[measure_col].mean(), 2),
                    "min_month": group.loc[
                        group[measure_col].idxmin(), time_col
                    ],
                    "max_month": group.loc[
                        group[measure_col].idxmax(), time_col
                    ],
                    "min_val": round(group[measure_col].min(), 2),
                    "max_val": round(group[measure_col].max(), 2),
                }
                for name, group in grouped
            }

    return summary
```

### What the Synthesizer Actually Sees

Instead of 24 rows, the synthesizer receives this compact summary:

```json
{
  "row_count": 24,
  "columns": [
    { "name": "month", "type": "date" },
    { "name": "customer_type", "type": "string" },
    { "name": "total_sales", "type": "number" }
  ],
  "sample_rows": {
    "first_5": [
      { "month": "2025-03-01", "customer_type": "New", "total_sales": 142000 },
      { "month": "2025-03-01", "customer_type": "Repeat", "total_sales": 318000 },
      { "month": "2025-04-01", "customer_type": "New", "total_sales": 156000 },
      { "month": "2025-04-01", "customer_type": "Repeat", "total_sales": 335000 },
      { "month": "2025-05-01", "customer_type": "New", "total_sales": 139000 }
    ],
    "last_5": ["..."]
  },
  "total_sales_stats": {
    "sum": 5834000, "mean": 243083, "min": 128000, "max": 352000
  },
  "customer_type_values": ["New", "Repeat"],
  "series_summary": {
    "New": {
      "total": 1837000, "mean": 153083,
      "min_month": "2025-12-01", "max_month": "2025-07-01",
      "min_val": 128000, "max_val": 182000
    },
    "Repeat": {
      "total": 3997000, "mean": 333083,
      "min_month": "2025-12-01", "max_month": "2025-08-01",
      "min_val": 315000, "max_val": 352000
    }
  }
}
```

-----

## 4. Synthesizer Agent

The synthesizer receives the original question, the planner output
(including presentation_intent), and the data summary (not the full
result set). It produces the narrative AND the chart/table config.

The chart config is produced by the synthesizer because it already
understands the data structure from writing the narrative — mapping
columns to axes is trivial incremental work. No separate deterministic
mapping layer is needed.

### System Prompt

```
You are the Synthesizer for a conversational analytics system in a
corporate banking environment.

## Input

You will receive:
- The user's original question
- The planner's output (including complexity_tier and presentation_intent)
- One or more DATA SUMMARIES (not raw result sets) containing row count,
  column metadata, sample rows, aggregate statistics, and per-series
  breakdowns

## Your Responsibilities

1. Write a narrative analytical summary
2. Produce a chart_config or table_config (if applicable)

## Narrative Rules

HARD RULES — violating these is a compliance failure:
- NEVER give prescriptive advice (no "you should", "consider", "I recommend")
- NEVER speculate about causes not directly evidenced by the data
- NEVER fabricate numbers — every figure must come from the data summary
- NEVER reference internal system details (SQL, table names, column names)

STYLE:
- Lead with the headline insight — the single most important finding
- Include specific numbers to support claims
- Call out notable patterns, trends, inflection points, or anomalies
- Keep it to 2-4 sentences for simple/moderate queries
- Use plain business language, no jargon
- Write in past tense for historical data, present for current state

## Chart Configuration

When presentation_intent.display_type is "chart", produce a chart_config
by mapping the result columns to visual roles. You already understand
the data's structure from writing the narrative — use that same
understanding to fill out:

{
  "type": "<from presentation_intent.chart_type>",
  "x": "<column name for x-axis>",
  "y": "<column name or array of column names for y-axis>",
  "series": "<column name for categorical split, or null>",
  "x_label": "<human-readable axis label>",
  "y_label": "<human-readable axis label>",
  "y_format": "currency" | "number" | "percent"
}

OVERRIDE RULES — apply these before producing chart_config:
- If the x-axis has fewer than 3 distinct values → set chart_config to null
  (chart adds no value, narrative is sufficient)
- If series would produce more than 10 lines/bars → set chart_config to null
  and set table_config to { "style": "simple" } instead
- If any data quality issue is apparent (all nulls, single repeated value)
  → set chart_config to null and note the issue in the narrative

## Table Configuration

When presentation_intent.display_type is "table", OR when a chart override
triggers a downgrade, produce a table_config:

{
  "style": "simple" | "ranked" | "comparison",
  "columns": [
    {
      "key": "<column name from result set>",
      "label": "<human-readable header>",
      "format": "currency" | "number" | "percent" | "date" | "string",
      "align": "left" | "right"
    }
  ],
  "sort_by": "<column name>" | null,
  "sort_dir": "asc" | "desc" | null,
  "show_rank": true | false
}

## Output Schema

Respond with valid JSON:

{
  "narrative": "<analytical summary>",
  "chart_config": { ... } | null,
  "table_config": { ... } | null
}
```

### Synthesizer Input

The synthesizer receives data summaries, NOT full result sets. The summary
is built by the deterministic `build_data_summary` function from Section 3.

```json
{
  "original_question": "What were my sales by month for the last year split by new and repeat customers?",
  "planner_output": {
    "complexity_tier": "simple",
    "intent": "Monthly sales totals for the trailing 12 months, broken down by customer type (new vs repeat)",
    "presentation_intent": {
      "display_type": "chart",
      "chart_type": "line",
      "rationale": "Time series (monthly) with a categorical split (customer_type)"
    }
  },
  "data_summaries": [
    {
      "subtask_id": "st_1",
      "row_count": 24,
      "columns": [
        { "name": "month", "type": "date" },
        { "name": "customer_type", "type": "string" },
        { "name": "total_sales", "type": "number" }
      ],
      "sample_rows": {
        "first_5": [
          { "month": "2025-03-01", "customer_type": "New", "total_sales": 142000 },
          { "month": "2025-03-01", "customer_type": "Repeat", "total_sales": 318000 },
          { "month": "2025-04-01", "customer_type": "New", "total_sales": 156000 },
          { "month": "2025-04-01", "customer_type": "Repeat", "total_sales": 335000 },
          { "month": "2025-05-01", "customer_type": "New", "total_sales": 139000 }
        ],
        "last_5": ["..."]
      },
      "total_sales_stats": {
        "sum": 5834000, "mean": 243083, "min": 128000, "max": 352000
      },
      "customer_type_values": ["New", "Repeat"],
      "series_summary": {
        "New": {
          "total": 1837000, "mean": 153083,
          "min_month": "2025-12-01", "max_month": "2025-07-01",
          "min_val": 128000, "max_val": 182000
        },
        "Repeat": {
          "total": 3997000, "mean": 333083,
          "min_month": "2025-12-01", "max_month": "2025-08-01",
          "min_val": 315000, "max_val": 352000
        }
      }
    }
  ]
}
```

### Synthesizer Output

The synthesizer only outputs the narrative and config objects. Raw data
bypasses the LLM entirely and goes straight from the SQL result set to
the frontend.

```json
{
  "narrative": "Over the last 12 months, total sales were $5.8M, with repeat customers consistently generating roughly 70% of monthly revenue. New customer sales peaked in July at $182K before declining through Q4 to a low of $128K in December, while repeat customer revenue remained stable in the $315K–$352K range. Both segments have shown modest recovery since January.",

  "chart_config": {
    "type": "line",
    "x": "month",
    "y": "total_sales",
    "series": "customer_type",
    "x_label": "Month",
    "y_label": "Sales",
    "y_format": "currency"
  },

  "table_config": null
}
```

### Chart Config Validation (deterministic, post-LLM)

After the synthesizer produces chart_config, a lightweight validation
confirms the column names actually exist in the result set. If validation
fails, the chart is dropped and the narrative stands alone.

```python
def validate_chart_config(config: dict, columns: list[str]) -> bool:
    if config["x"] not in columns:
        return False
    y = config["y"] if isinstance(config["y"], list) else [config["y"]]
    if not all(col in columns for col in y):
        return False
    if config.get("series") and config["series"] not in columns:
        return False
    return True
```

-----

## 5. SSE Stream to Frontend

The pipeline emits events in this order. The frontend renders
progressively as each event arrives. Note that chart data and raw data
bypass the LLM — they go straight from the SQL result set to the frontend.

```python
async def run_pipeline(question: str, conversation_context: list):
    planner_output = await planner.plan(question, conversation_context)

    # ── STATUS ──────────────────────────────────────
    yield sse_event({
        "type": "status",
        "payload": { "step": "Analyzing question..." }
    })

    # ── SQL EXECUTION ───────────────────────────────
    yield sse_event({
        "type": "status",
        "payload": { "step": "Querying data..." }
    })

    # Single subtask for simple/moderate, parallel for complex
    if len(planner_output.subtasks) == 1:
        results = [await executor.execute(planner_output.subtasks[0])]
    else:
        results = await asyncio.gather(*[
            executor.execute(st) for st in planner_output.subtasks
        ])

    # Optionally expose SQL for transparency
    for result in results:
        yield sse_event({
            "type": "sql",
            "payload": {
                "question": result.subtask_question,
                "query": result.sql
            }
        })

    # ── VALIDATION ──────────────────────────────────
    for result in results:
        validation = validate_sql(result.sql, semantic_model)
        if not validation.passed:
            yield sse_event({
                "type": "error",
                "payload": {
                    "message": "I wasn't able to generate a valid query "
                               "for that question. Could you try rephrasing it?"
                }
            })
            return

    # ── BUILD DATA SUMMARIES ────────────────────────
    # The synthesizer gets compact summaries, NOT full result sets.
    # This keeps context size predictable regardless of row count.
    summaries = [
        build_data_summary(r, planner_output.presentation_intent)
        for r in results
    ]

    # ── SYNTHESIS ───────────────────────────────────
    # Check if template synthesis applies (simple tier, small result)
    if (
        planner_output.complexity_tier == "simple"
        and len(results) == 1
        and template_synthesizer.can_handle(results[0])
        and planner_output.presentation_intent.display_type == "inline"
    ):
        response_text = template_synthesizer.synthesize(question, results[0])
        yield sse_event({
            "type": "answer",
            "payload": { "content": response_text, "complete": True }
        })
    else:
        # LLM synthesis — gets summaries, not raw data
        async for chunk in synthesizer.stream(
            question, planner_output, summaries
        ):
            yield sse_event({
                "type": "answer",
                "payload": { "content": chunk, "complete": False }
            })
        yield sse_event({
            "type": "answer",
            "payload": { "content": "", "complete": True }
        })

    # ── SYNTHESIZER STRUCTURED OUTPUT ───────────────
    # Get chart_config / table_config from the synthesizer
    structured = synthesizer.get_structured_output()

    # ── VISUALIZATION ───────────────────────────────
    # Chart data comes from the SQL result set, NOT the synthesizer.
    # Only the first (primary) subtask's result set gets visualized.
    if structured.chart_config:
        primary_result = results[0]
        col_names = [c["name"] for c in primary_result.columns]

        if validate_chart_config(structured.chart_config, col_names):
            yield sse_event({
                "type": "visualization",
                "payload": {
                    "chart_type": structured.chart_config["type"],
                    "config": structured.chart_config,
                    "data": primary_result.rows
                }
            })

    # ── DATA EXPORT ─────────────────────────────────
    # Raw data goes straight from SQL results to frontend.
    # Uses datasets array to support multi-subtask tabbed view.
    yield sse_event({
        "type": "data",
        "payload": {
            "datasets": [
                {
                    "label": st.question,
                    "columns": r.columns,
                    "rows": r.rows,
                }
                for st, r in zip(planner_output.subtasks, results)
            ]
        }
    })

    # ── CONFIDENCE + METADATA ───────────────────────
    confidence = compute_confidence(planner_output, results)
    yield sse_event({
        "type": "done",
        "payload": {
            "confidence": confidence.score,
            "confidence_level": confidence.level,
            "execution_time_ms": sum(r.execution_time_ms for r in results)
        }
    })

    # ── FOLLOW-UP SUGGESTIONS ───────────────────────
    yield sse_event({
        "type": "suggestions",
        "payload": {
            "questions": [
                "How does this compare to the prior year?",
                "Which regions are driving the new customer decline?",
                "What's the average order value by customer type?"
            ]
        }
    })
```

-----

## 6. Frontend Rendering

The frontend receives the SSE events and renders them into a chat
message component. Here’s how the final message looks structurally:

### TypeScript Types

```typescript
// These match the SSE event discriminated union you already have

interface ChartConfig {
  type: "line" | "bar" | "stacked_bar" | "grouped_bar";
  x: string;
  y: string | string[];              // single column or array for multi-measure
  series: string | null;
  x_label: string;
  y_label: string;
  y_format: "currency" | "number" | "percent";
}

interface TableColumnConfig {
  key: string;
  label: string;
  format: "currency" | "number" | "percent" | "date" | "string";
  align: "left" | "right";
}

interface TableConfig {
  style: "simple" | "ranked" | "comparison";
  columns: TableColumnConfig[];
  sort_by: string | null;
  sort_dir: "asc" | "desc" | null;
  show_rank: boolean;
}

interface DatasetPayload {
  label: string;
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
}

interface AssistantMessage extends BaseMessage {
  role: "assistant";
  content: string;                    // narrative text
  sql?: string;                       // expandable SQL panel
  confidence?: number;
  chartConfig?: ChartConfig | null;   // drives chart rendering
  chartData?: Record<string, unknown>[]; // raw rows for the chart (from primary result set)
  tableConfig?: TableConfig | null;   // drives table styling
  datasets?: DatasetPayload[];        // raw data for all subtasks (for export/inspection)
  suggestions?: string[];             // follow-up chips
}
```

### React Rendering (simplified)

```tsx
function AssistantMessageBubble({ message }: { message: AssistantMessage }) {
  const [showRawData, setShowRawData] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Narrative — always present */}
      <div className="prose">
        <StreamingText content={message.content} />
      </div>

      {/* 2. Chart — only if chart_config is present and validated */}
      {message.chartConfig && message.chartData && (
        <AnalyticsChart
          config={message.chartConfig}
          data={message.chartData}
        />
      )}

      {/* 3. Styled table — only if table_config is present and no chart */}
      {message.tableConfig && !message.chartConfig && message.datasets?.[0] && (
        <StyledTable
          config={message.tableConfig}
          data={message.datasets[0].rows}
        />
      )}

      {/* 4. Raw data toggle — supports tabbed view for multi-subtask */}
      {message.datasets && message.datasets.length > 0 && (
        <div>
          <button
            onClick={() => setShowRawData(!showRawData)}
            className="text-sm text-blue-600 hover:underline"
          >
            {showRawData ? "Hide data" : "View data"}
          </button>
          {showRawData && (
            message.datasets.length > 1 ? (
              <TabbedDataView datasets={message.datasets} />
            ) : (
              <DataTable
                columns={message.datasets[0].columns}
                rows={message.datasets[0].rows}
              />
            )
          )}
        </div>
      )}

      {/* 5. Confidence badge */}
      {message.confidence !== undefined && (
        <ConfidenceBadge score={message.confidence} />
      )}

      {/* 6. Follow-up suggestions */}
      {message.suggestions && (
        <div className="flex flex-wrap gap-2">
          {message.suggestions.map((q) => (
            <button
              key={q}
              onClick={() => sendMessage(q)}
              className="text-sm px-3 py-1 rounded-full bg-gray-100
                         hover:bg-gray-200 transition"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

### The AnalyticsChart Component

```tsx
import { LineChart, Line, BarChart, Bar, XAxis, YAxis,
         CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface AnalyticsChartProps {
  config: ChartConfig;
  data: Record<string, unknown>[];
}

function AnalyticsChart({ config, data }: AnalyticsChartProps) {
  // Determine if this is a multi-measure chart (y is array) or series split
  const yColumns = Array.isArray(config.y) ? config.y : [config.y];
  const isMultiMeasure = Array.isArray(config.y) && config.y.length > 1;

  // Pivot data if there's a series column (single measure, categorical split)
  // Recharts wants: [{ month: "Mar", New: 142000, Repeat: 318000 }, ...]
  // We have:        [{ month: "Mar", customer_type: "New", total_sales: 142000 }, ...]
  const chartData = config.series && !isMultiMeasure
    ? pivotData(data, config.x, yColumns[0], config.series)
    : data;

  // Determine the series to render as separate lines/bars
  const seriesValues = isMultiMeasure
    ? yColumns                    // each measure is its own line
    : config.series
      ? [...new Set(data.map((d) => d[config.series!] as string))]
      : yColumns;                 // single measure, single line

  const colors = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

  const formatValue = (value: number) => {
    if (config.y_format === "currency") {
      return value >= 1000
        ? `$${(value / 1000).toFixed(0)}K`
        : `$${value}`;
    }
    if (config.y_format === "percent") return `${value}%`;
    return value.toLocaleString();
  };

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  };

  if (config.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey={config.x}
            tickFormatter={formatDate}
            tick={{ fontSize: 12 }}
          />
          <YAxis
            tickFormatter={formatValue}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            formatter={(value: number) => formatValue(value)}
            labelFormatter={formatDate}
          />
          <Legend />
          {seriesValues.map((series, i) => (
            <Line
              key={series}
              type="monotone"
              dataKey={series}
              stroke={colors[i % colors.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
              name={series}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // ... bar chart variants follow the same pattern
  return null;
}

// Pivot helper: row-per-category → columns-per-category
function pivotData(
  data: Record<string, unknown>[],
  xKey: string,
  yKey: string,
  seriesKey: string
): Record<string, unknown>[] {
  const grouped = new Map<string, Record<string, unknown>>();

  for (const row of data) {
    const xVal = row[xKey] as string;
    if (!grouped.has(xVal)) {
      grouped.set(xVal, { [xKey]: xVal });
    }
    const seriesVal = row[seriesKey] as string;
    grouped.get(xVal)![seriesVal] = row[yKey];
  }

  return Array.from(grouped.values());
}
```

### Override Example

**Query:** “Revenue by cost center”

**Planner** → `display_type: "chart"`, `chart_type: "bar"` (breakdown, expects < 8 categories)
**Result set** returns 34 cost centers.
**Synthesizer** applies override: too many categories → downgrades to table.

```json
{
  "narrative": "Revenue across 34 cost centers totaled $18.2M. The top 5 cost centers account for 61% of total revenue, led by Commercial Lending at $3.8M.",
  "chart_config": null,
  "table_config": {
    "style": "simple",
    "columns": [ ... ],
    "sort_by": "revenue",
    "sort_dir": "desc",
    "show_rank": false
  }
}
```