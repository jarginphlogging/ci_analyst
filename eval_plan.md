# Cortex Analyst Evaluation Plan — Three-Tier Architecture

## The Core Problem

Each evaluation tier has access to different information. This changes what you can evaluate and how.

```
                        Has ground     Can use      Blocks
                        truth?         LLM judge?   response?    Runs when?
                        ─────────      ──────────   ─────────    ──────────
Tier 1: Inline          No             No           Yes          Every request
Tier 2: Async Prod      No             Yes          No           After response
Tier 3: Golden Dataset  Yes            Yes          No           CI/CD + nightly
```

This means:

- **Tier 1** can only ask: "Is this output structurally valid?"
- **Tier 2** can only ask: "Is this output internally consistent with the other pipeline outputs?"
- **Tier 3** can ask: "Is this output actually correct?"

The judge gets different context at each tier. A hallucination eval at Tier 2 checks whether the synthesis is grounded in the SQL results the pipeline produced (which might themselves be wrong). The same eval at Tier 3 checks whether the synthesis matches the known-correct answer. Same evaluator template, fundamentally different meaning.

---

## Pipeline Nodes

```
User Question → [1. Decompose] → [2. SQL Gen] → [3. Execute] → [4. Summarize] → [5. Synthesize]
```

---

## Tier 1: Inline Checks

**Context available**: Only the current node's input and output. No ground truth. No LLM judge (too slow).
**Latency budget**: ~200ms total across all checks.
**Purpose**: Catch structurally broken outputs before they propagate downstream or reach the user.
**Implementation**: Python functions in the pipeline code. Not Phoenix evaluators — these run in the hot path.

| Node | Check | What It Looks At | Fail Action |
|------|-------|-----------------|-------------|
| **Decompose** | Sub-question count | Output has 1-5 sub-questions (not 0, not 20) | Return error |
| **Decompose** | Format valid | Output parses as expected structure (list of strings) | Return error |
| **SQL Gen** | Syntax valid | `sqlparse.parse()` succeeds, returns a SELECT statement | Skip this sub-question |
| **SQL Gen** | Schema refs valid | All table/column names exist in semantic model | Skip this sub-question |
| **Execute** | Non-empty result | Query returned at least 1 row (for queries that should) | Surface warning to user |
| **Execute** | Result size sane | Row count < 10,000; no single cell > 1MB | Truncate + warn |
| **Summarize** | Non-empty output | Summary is not blank or error message | Return raw data instead |
| **Synthesize** | Non-empty output | Final answer exists and is > 20 characters | Return summaries directly |
| **Synthesize** | PII filter | No SSN, account number patterns in output | Redact + warn |

```python
# Example: inline checks are plain Python, not Phoenix evaluators
def inline_sql_checks(sql: str, semantic_model: dict) -> tuple[bool, str]:
    """Returns (pass, reason). Runs in the hot path."""
    
    # Syntax check
    try:
        parsed = sqlparse.parse(sql)
        if not parsed or parsed[0].get_type() != "SELECT":
            return False, "SQL did not parse as a SELECT statement"
    except Exception:
        return False, "SQL failed to parse"
    
    # Schema check
    tables_in_sql = extract_table_names(parsed[0])
    valid_tables = set(semantic_model["tables"].keys())
    invalid = tables_in_sql - valid_tables
    if invalid:
        return False, f"Unknown tables referenced: {invalid}"
    
    return True, "passed"
```

**What Tier 1 cannot tell you**: Whether the SQL is *correct*. A syntactically valid query against real tables can still return completely wrong data. That's Tier 2 and 3's job.

---

## Tier 2: Async Production Evaluation

**Context available**: The full trace — every node's input and output. But NO ground truth. You don't know what the right SQL was, what the right answer was, or what the right decomposition was.
**Latency impact**: Zero (runs after response is delivered).
**Purpose**: Assess internal consistency. "Given what the pipeline produced at each stage, do the outputs make sense relative to each other?"
**Implementation**: Phoenix online evals + scheduled batch via `llm_classify`.

### What the judge sees at each node (no ground truth)

| Node | Judge Input | Judge Question | Phoenix Evaluator |
|------|------------|---------------|-------------------|
| **Decompose** | Input: user question. Output: sub-questions | "Do these sub-questions, if answered, fully address the original question? Are any redundant or off-topic?" | Custom LLM eval via `create_classifier` |
| **SQL Gen** | Input: sub-question. Output: generated SQL. Also available: execution results | "Does this SQL query appropriately answer the question, considering its results?" | Pre-built `SQL_GEN_EVAL` (template uses `{question}`, `{query_gen}`, `{response}`) |
| **Execute** | Input: SQL. Output: result set | N/A — no LLM eval needed. Deterministic check: did the query error? Row count reasonable? | Code evaluator (already covered in Tier 1, logged to trace) |
| **Summarize** | Input: result tables. Output: summary text | "Is this summary comprehensive, concise, and coherent relative to the source data?" | Pre-built `SUMMARIZATION_EVAL` (template uses `{input}`, `{output}`) |
| **Synthesize** | Input: summaries + user question. Output: final answer | "Is this answer factual or hallucinated based on the provided context?" AND "Does this answer correctly address the question?" | Pre-built `HALLUCINATION_EVAL` + `QA_CORRECTNESS_EVAL` |

### Critical distinction: what "hallucination" means without ground truth

At Tier 2, the hallucination eval checks: *"Is the synthesis grounded in the SQL results and summaries the pipeline produced?"*

It does NOT check: *"Is the synthesis factually correct?"*

If Cortex Analyst generated the wrong SQL, the execution returned wrong data, the summary faithfully described that wrong data, and the synthesis faithfully reported the wrong summary — **Tier 2 will score this as non-hallucinated**. Because internally, the pipeline was consistent. It was consistently wrong.

Only Tier 3 (with ground truth) can catch this. This is why you need all three tiers.

### Implementation

```python
# tier2_async_eval.py
"""
Attach as Phoenix online evaluations, or run as a scheduled batch.
"""
import phoenix as px
from phoenix.evals import (
    llm_classify, create_classifier, LLM,
    SQL_GEN_EVAL_PROMPT_TEMPLATE, SQL_GEN_EVAL_PROMPT_RAILS_MAP,
    HALLUCINATION_PROMPT_TEMPLATE, HALLUCINATION_PROMPT_RAILS_MAP,
    QA_PROMPT_TEMPLATE, QA_PROMPT_RAILS_MAP,
    SUMMARIZATION_PROMPT_TEMPLATE, SUMMARIZATION_PROMPT_RAILS_MAP,
)
from phoenix.trace import SpanEvaluations

client = px.Client()
judge = LLM(provider="openai", model="gpt-4o-mini")

# ─── Pull recent traces ───
spans_df = client.get_spans_dataframe(
    project_name="cortex-analyst-pipeline",
    start_time=datetime.now() - timedelta(hours=1),
)

# ─── Decomposition quality (custom LLM eval — no pre-built for this) ───
decompose_df = spans_df[spans_df["name"] == "decompose"].copy()
decompose_df = decompose_df.rename(columns={
    "attributes.input.value": "question",
    "attributes.output.value": "sub_questions",
})

decomposition_evaluator = create_classifier(
    name="decomposition_quality",
    prompt_template=(
        "A user asked: {question}\n\n"
        "The system decomposed this into sub-questions: {sub_questions}\n\n"
        "Evaluate: Do these sub-questions fully cover the original question? "
        "Are any redundant or off-topic? Would answering all of them "
        "adequately address the user's intent?"
    ),
    llm=judge,
    choices={"complete": 1.0, "partial": 0.5, "poor": 0.0},
)

decomp_results = decomposition_evaluator.evaluate(dataframe=decompose_df)

# ─── SQL Generation (pre-built) ───
# SQL_GEN_EVAL expects: {question}, {query_gen}, {response}
# question = the sub-question, query_gen = generated SQL, response = execution results
sql_gen_df = spans_df[spans_df["name"].str.startswith("sql_generation")].copy()
sql_gen_df = sql_gen_df.rename(columns={
    "attributes.input.value": "question",
    "attributes.output.value": "query_gen",
})
# Join execution results from the corresponding sql_execution span
# (join on trace_id + sub-question index to get the response column)

sql_results = llm_classify(
    dataframe=sql_gen_df,
    template=SQL_GEN_EVAL_PROMPT_TEMPLATE,
    model=judge,
    rails=list(SQL_GEN_EVAL_PROMPT_RAILS_MAP.values()),
    provide_explanation=True,
    concurrency=20,
)

# ─── Summarization (pre-built) ───
# Expects: {input} = source data, {output} = summary text
summary_df = spans_df[spans_df["name"] == "summarize"].copy()
summary_df = summary_df.rename(columns={
    "attributes.input.value": "input",   # The table data
    "attributes.output.value": "output", # The summary
})

summarization_results = llm_classify(
    dataframe=summary_df,
    template=SUMMARIZATION_PROMPT_TEMPLATE,
    model=judge,
    rails=list(SUMMARIZATION_PROMPT_RAILS_MAP.values()),
    provide_explanation=True,
    concurrency=20,
)

# ─── Synthesis: Hallucination + QA Correctness (pre-built) ───
# Hallucination expects: {input} = question, {output} = answer, {context} = source data
# QA expects: {query} = question, {reference} = context, {sampled_answer} = answer
synth_df = spans_df[spans_df["name"] == "synthesize"].copy()
synth_df = synth_df.rename(columns={
    "attributes.input.value": "input",
    "attributes.output.value": "output",
})
# context = the summaries/data that the synthesis was based on

hallucination_results = llm_classify(
    dataframe=synth_df,
    template=HALLUCINATION_PROMPT_TEMPLATE,
    model=judge,
    rails=list(HALLUCINATION_PROMPT_RAILS_MAP.values()),
    provide_explanation=True,
    concurrency=20,
)

qa_results = llm_classify(
    dataframe=synth_df,
    template=QA_PROMPT_TEMPLATE,
    model=judge,
    rails=list(QA_PROMPT_RAILS_MAP.values()),
    provide_explanation=True,
    concurrency=20,
)

# ─── Log all scores back to Phoenix ───
client.log_evaluations(
    SpanEvaluations(dataframe=decomp_results, eval_name="Decomposition Quality"),
    SpanEvaluations(dataframe=sql_results, eval_name="SQL Correctness"),
    SpanEvaluations(dataframe=summarization_results, eval_name="Summarization"),
    SpanEvaluations(dataframe=hallucination_results, eval_name="Hallucination"),
    SpanEvaluations(dataframe=qa_results, eval_name="QA Correctness"),
)

# ─── Flag failures for review ───
hallucinated = hallucination_results[hallucination_results["label"] == "hallucinated"]
bad_sql = sql_results[sql_results["label"] == "incorrect"]
flagged = pd.concat([hallucinated, bad_sql])
if not flagged.empty:
    flagged.to_csv(f"flagged/review_{datetime.now().strftime('%Y%m%d')}.csv")
```

### Feedback Flywheel

Flagged Tier 2 failures become candidates for the golden dataset. During weekly review:
1. Pull flagged traces
2. Determine the correct answer manually
3. Add to golden dataset with ground truth
4. Next Tier 3 run catches that failure class forever

This is how Tier 2 feeds Tier 3 — production failures with no ground truth get investigated, then promoted to ground-truth examples.

---

## Tier 3: Golden Dataset Evaluation

**Context available**: Full trace outputs AND ground truth (expected decomposition, expected SQL, expected results, expected answer).
**Latency impact**: Zero (runs in CI or on schedule, never in prod).
**Purpose**: Measure actual correctness. "Is the output right?"
**Implementation**: Phoenix Datasets + Experiments.

### What the judge sees at each node (WITH ground truth)

| Node | Judge Input | Judge Question | Evaluator |
|------|------------|---------------|-----------|
| **Decompose** | Output: actual sub-questions. Ground truth: expected sub-questions | "Do the actual sub-questions cover the same ground as the expected ones?" + Deterministic: set intersection of topics | LLM eval + code eval |
| **SQL Gen** | Output: generated SQL. Ground truth: expected SQL + expected results | "Does this SQL answer the question?" + Deterministic: execute both, compare result sets | Pre-built `SQL_GEN_EVAL` + `execution_accuracy` code eval |
| **Execute** | Output: actual result set. Ground truth: expected result set | Deterministic only: datacompy comparison of actual vs expected DataFrames | `execution_accuracy` code eval |
| **Summarize** | Output: summary. Ground truth: expected answer containing key values | "Is the summary good?" + Deterministic: do expected key values appear? | Pre-built `SUMMARIZATION_EVAL` + `key_value_presence` code eval |
| **Synthesize** | Output: final answer. Ground truth: expected answer + expected data | "Is this correct based on the reference?" + "Is this hallucinated?" | Pre-built `QA_CORRECTNESS` (with reference!) + `HALLUCINATION_EVAL` |

### The key difference: the judge now has a reference answer

At Tier 2, the QA eval asks: *"Does this answer seem reasonable given the data the pipeline produced?"*

At Tier 3, the QA eval asks: *"Does this answer match the known-correct answer?"*

The hallucination eval is even more powerful here — the context isn't just "what the pipeline produced" but "what the correct data actually is." So if Cortex Analyst generated wrong SQL that returned wrong data that was faithfully summarized (passing Tier 2), Tier 3 catches it because the result set doesn't match the golden result set and the final answer doesn't match the golden answer.

### Implementation

```python
# tier3_golden_eval.py
"""
Run via Phoenix Experiments in CI/CD or nightly.
"""
import phoenix as px
from phoenix.experiments import run_experiment
from phoenix.evals import create_evaluator
import datacompy
import pandas as pd

client = px.Client()
dataset = client.get_dataset(name="cortex-analyst-golden-v1")

# ─── The task: run a question through the pipeline ───
async def pipeline_task(input):
    question = input["input"]
    
    sub_questions = await decompose_question(question)
    generated_sql = await call_cortex_analyst(question)
    result_df = await execute_sql(generated_sql)
    summary = await summarize_tables([result_df])
    final_answer = await synthesize_insights(question, summary)
    
    return {
        "sub_questions": sub_questions,
        "generated_sql": generated_sql,
        "result_row_count": len(result_df),
        "result_columns": list(result_df.columns),
        "summary": summary,
        "final_answer": final_answer,
    }

# ─── Code evaluators (deterministic, with ground truth) ───

@create_evaluator(name="execution_accuracy", kind="CODE")
def execution_accuracy(output, expected) -> float:
    """Execute generated SQL and golden SQL, compare result sets."""
    conn = get_snowflake_connection()
    try:
        gen_df = pd.read_sql(output["generated_sql"], conn)
        exp_df = pd.read_sql(expected["expected_output"], conn)  # Golden SQL
        
        if len(exp_df) == 0:
            return 1.0 if len(gen_df) == 0 else 0.0
        
        comparison = datacompy.Compare(
            gen_df, exp_df,
            join_columns=list(exp_df.columns),
            abs_tol=0.01,
        )
        return comparison.intersect_rows_count / len(exp_df)
    except Exception:
        return 0.0

@create_evaluator(name="decomposition_coverage", kind="CODE")
def decomposition_coverage(output, expected) -> float:
    """What fraction of expected sub-question topics are covered?"""
    actual_topics = set(t.lower().strip() for t in output.get("sub_questions", []))
    expected_topics = set(t.lower().strip() for t in expected.get("expected_decomposition", []))
    
    if not expected_topics:
        return 1.0  # No expected decomposition defined for this example
    
    covered = len(actual_topics & expected_topics)
    return covered / len(expected_topics)

@create_evaluator(name="key_value_presence", kind="CODE")
def key_value_presence(output, expected) -> float:
    """Do expected key values appear in the final answer?"""
    answer = output.get("final_answer", "").lower()
    must_contain = expected.get("must_contain", [])
    
    if not must_contain:
        return 1.0
    
    found = sum(1 for kw in must_contain if kw.lower() in answer)
    return found / len(must_contain)

# ─── Run the experiment ───
# Phoenix pre-built LLM evals (SQL gen, hallucination, QA, summarization)
# are attached alongside the code evaluators.
# The LLM evals now have ground truth in the expected column,
# which gets passed as reference/context to the judge templates.

experiment = run_experiment(
    dataset=dataset,
    task=pipeline_task,
    evaluators=[
        execution_accuracy,
        decomposition_coverage,
        key_value_presence,
        # LLM evaluators also attached here — they receive both
        # the task output AND the expected output from the dataset,
        # so the judge can compare against ground truth
    ],
    experiment_name="pipeline-v2.1-new-decomposition-prompt",
)
```

### CI/CD Quality Gate

```python
# quality_gate.py — fails the build if Tier 3 scores regress

THRESHOLDS = {
    "execution_accuracy": 0.80,      # 80% of golden queries produce correct results
    "decomposition_coverage": 0.75,  # 75% topic coverage on decomposition
    "key_value_presence": 0.85,      # 85% of expected values appear in answers
    "SQL Correctness": 0.80,         # 80% judged correct by LLM
    "Hallucination": 0.85,           # 85% judged factual
    "QA Correctness": 0.80,          # 80% judged correct
    "Summarization": 0.80,           # 80% judged good
}
```

---

## How the Three Tiers Work Together

```
              Tier 1 (Inline)              Tier 2 (Async)              Tier 3 (Golden)
              ─────────────────            ─────────────────           ─────────────────
Ground truth  None                         None                        Full
Judge?        No                           Yes                         Yes
Judge sees    N/A                          Pipeline's own outputs      Pipeline outputs + correct answers
Catches       Broken outputs               Internally inconsistent     Actually wrong outputs
              (malformed SQL,                outputs (hallucinated       (correct-looking SQL that
              empty results,                claims, off-topic answers,  returns wrong data,
              PII leaks)                    poor summaries)             missing key facts)

Speed         ~200ms total                 Minutes (batched)           Minutes (CI/CD)
Frequency     Every request                Hourly/nightly              On PR + nightly

Example       SQL references a table       Synthesis claims "revenue   Golden says revenue was $4.2M,
catch         that doesn't exist in        grew 15%" but the SQL       pipeline says $3.8M because
              the semantic model           results show 15% — the      Cortex Analyst joined the
              → blocked before             claim is grounded but       wrong table → Tier 2 sees
              execution                    the original SQL may        consistency, Tier 3 catches
                                           have been wrong             the actual error
```

### The flow between tiers

```
Production request
       │
       ▼
   Tier 1: Inline ──── BLOCK if broken
       │
       ▼
   Deliver response to user
       │
       ▼
   Tier 2: Async eval ──── FLAG if inconsistent
       │                         │
       │                    Weekly review
       │                         │
       │                    Confirmed failures
       │                         │
       │                         ▼
       │                    Add to golden dataset
       │                         │
       ▼                         ▼
   Tier 3: Golden eval ──── GATE CI/CD if incorrect
       │
       ▼
   Catches the class of failure forever
```

---

## Phase 1 vs Phase 2

### Phase 1: Phoenix Only

All three tiers, implemented with Phoenix + inline Python:

- **Tier 1**: Inline Python functions in pipeline code
- **Tier 2**: Phoenix online evals + scheduled `llm_classify` batch
- **Tier 3**: Phoenix Datasets + `run_experiment()` + CI quality gate
- **All nodes evaluated**: Deterministic + LLM at every stage
- **Human loop**: Span Replay, Prompt Playground, weekly annotation, eval-the-evals

### Phase 2: Fill Gaps Only When Phoenix Proves Insufficient

| Gap | When to Act | Tool |
|-----|------------|------|
| Tier 3 needs pytest-style assertions | Phoenix experiment SDK doesn't give clean CI pass/fail | DeepEval |
| SQL eval has too many false negatives | Different-looking SQL scored wrong despite correct results | RAGAS SQLSemanticEquivalence |
| Need alerting on Tier 2 score drops | Dashboard isn't enough, need push notifications | Arize AX or webhook |
| Annotation volume outgrows Phoenix UI | Weekly review > 50 traces | Argilla |
| Need claim-level faithfulness decomposition | "Which specific claim in the synthesis was wrong?" | DeepEval FaithfulnessMetric or custom |

---

## Implementation Timeline

| Week | Focus | Deliverable |
|------|-------|-------------|
| 1 | Tracing all 5 stages + Tier 1 inline checks | Full traces in Phoenix; broken outputs blocked |
| 2 | 10 golden examples + execution_accuracy code eval | First Tier 3 experiment with scores |
| 3 | All Tier 2 LLM evals (SQL gen, hallucination, QA, summarization, decomposition) | Every node scored async on production traces |
| 4 | Expand golden dataset to 50 + all Tier 3 evaluators | Full Tier 3 regression suite |
| 5 | CI/CD quality gate + online evals attached to traces | PRs gated; production monitored continuously |
| 6 | First eval-the-evals: annotate 30 traces, compare vs judge | Calibrated, trustworthy scores |
| Ongoing | Weekly review → golden dataset growth → feedback flywheel | System compounds over time |