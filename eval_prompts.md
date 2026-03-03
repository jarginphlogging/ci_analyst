# Claude Code Prompts — Evaluation Pipeline Implementation

## How to Use This

These are **sequential prompts** for Claude Code. Run them in order. Each one builds on the output of the previous one. Don't skip ahead — later prompts assume the earlier work exists.

Before starting, drop the evaluation plan (`cortex_analyst_eval_plan_3tier.md`) into your repo root so Claude Code can reference it as context. You can also add it to your AGENTS.md or a dedicated `docs/` folder.

Each prompt is scoped to one session. Copy-paste the prompt, let Claude Code work, review the output, then move to the next one.

---

## Prompt 0: Orientation

> Read the evaluation plan in `docs/cortex_analyst_eval_plan_3tier.md` and my existing pipeline code. Map each pipeline stage (decompose, SQL generation, SQL execution, summarize, synthesize) to the actual functions/classes in my codebase. Don't change any code yet — just produce a brief mapping document at `docs/eval_code_mapping.md` that shows:
>
> 1. Which file and function handles each pipeline stage
> 2. What the inputs and outputs of each stage actually look like (types, data structures)
> 3. Where Phoenix tracing is already set up (if anywhere) and where it's missing
> 4. What the current Snowflake connection setup looks like
>
> I need this mapping before we start building so we're working with my actual code, not hypothetical examples.

**Why this prompt exists**: Claude Code needs to understand your codebase before writing eval code. This prevents it from generating code against an imagined architecture. Review the mapping doc carefully — correct anything wrong before proceeding.

---

## Prompt 1: Tracing

> Reference the mapping doc at `docs/eval_code_mapping.md`. Add Phoenix OpenTelemetry tracing to every pipeline stage. Specifically:
>
> **Setup:**
> - Install `arize-phoenix`, `arize-phoenix-otel`, `arize-phoenix-evals`, `openinference-instrumentation-openai` 
> - Create a `tracing.py` module that initializes Phoenix with our existing config (check if we already have Phoenix set up for our simpler chatbot — reuse that connection, don't create a new one)
> - Auto-instrument our Azure OpenAI calls via `OpenAIInstrumentor`
>
> **Manual spans on each pipeline stage:**
> - Wrap each stage function with `tracer.start_as_current_span()`
> - Set `input.value` and `output.value` attributes on every span
> - On SQL generation spans, also set `sql.query`
> - On execution spans, also set `result.row_count` and `result.columns`
> - On decomposition spans, also set `decomposition.count`
>
> **Important:**
> - Don't refactor the pipeline logic — just add tracing around the existing functions
> - If a stage is async, make sure the span context propagates correctly
> - Use the project name `cortex-analyst-pipeline`
> - Make sure the tracer initialization only runs once (not on every request)
>
> After implementing, tell me how to verify it's working (what should I see in the Phoenix UI).

---

## Prompt 2: Tier 1 — Inline Checks

> Reference `docs/eval_code_mapping.md`. Implement Tier 1 inline checks that run in the hot path of every request. These are plain Python functions — NOT Phoenix evaluators. They run before the response is delivered and can block or modify the pipeline's behavior.
>
> Create an `evaluation/inline_checks.py` module with these functions:
>
> **After decomposition:**
> - `check_decomposition(sub_questions: list) -> tuple[bool, str]`: Verify 1-5 sub-questions returned, output parses as expected structure. Return (pass, reason).
>
> **After SQL generation:**
> - `check_sql_syntax(sql: str) -> tuple[bool, str]`: Use `sqlparse` to verify it parses as a SELECT. Return (pass, reason).
> - `check_schema_refs(sql: str, semantic_model: dict) -> tuple[bool, str]`: Verify all table names in the SQL exist in our semantic model. Load valid table names from our `semantic_model.yaml`. Return (pass, reason).
>
> **After SQL execution:**
> - `check_result_sanity(result_df, sql: str) -> tuple[bool, str]`: Non-empty result for queries that should return data, row count < 10,000, no single cell > 1MB. Return (pass, reason).
>
> **After synthesis:**
> - `check_output_sanity(output: str) -> tuple[bool, str]`: Output exists, is > 20 characters, doesn't match known error patterns. Return (pass, reason).
> - `check_pii(output: str) -> tuple[bool, str]`: Regex for SSN patterns, account number patterns. Return (pass, reason).
>
> Then **integrate these into the pipeline code**:
> - Each check runs after its corresponding stage
> - Log check results as span events on the current OTEL span (so they show up in Phoenix traces)
> - If a SQL check fails, skip that sub-question and log a warning (don't crash the whole pipeline)
> - If the synthesis PII check fails, redact and add a warning to the response
>
> Install `sqlparse` if not already present. Use `pip install sqlparse`.
>
> Total latency budget for all inline checks: ~200ms. Keep them fast.

---

## Prompt 3: Golden Dataset

> Create the golden dataset infrastructure using Phoenix Datasets.
>
> **Create `evaluation/golden_dataset.py`:**
>
> Define a data structure for golden examples. Each example needs:
> - `input`: The user's natural language question
> - `expected_decomposition`: List of expected sub-questions (for decomposition eval)
> - `expected_sql`: The known-correct SQL query
> - `expected_answer`: The known-correct final answer text
> - `difficulty`: "simple" | "moderate" | "complex"
> - `must_contain`: List of key values that must appear in the answer
> - `category`: Business domain category (e.g., "revenue", "customers", "products")
>
> **Create `evaluation/golden_examples.yaml`:**
>
> Write 10 starter examples using our actual semantic model and real tables. Look at our `semantic_model.yaml` to understand what tables, columns, and business logic are available. Target:
> - 4 simple (single table, single aggregation)
> - 4 moderate (joins, grouping, time comparisons)
> - 2 complex (multi-step reasoning, conditional logic)
>
> Make the SQL realistic for our schema. Use actual table and column names.
>
> **Create `evaluation/upload_golden_dataset.py`:**
>
> A script that:
> 1. Loads examples from `golden_examples.yaml`
> 2. Uploads them to Phoenix as a dataset named `cortex-analyst-golden-v1`
> 3. Can be re-run to update the dataset when examples are added
>
> Use the Phoenix Python SDK (`px.Client().upload_dataset()`).

---

## Prompt 4: Tier 3 — Code Evaluators (Deterministic)

> Create deterministic code evaluators that run during Tier 3 golden dataset experiments. These evaluate actual correctness because they have access to ground truth.
>
> **Create `evaluation/code_evaluators.py`:**
>
> Use Phoenix's `@create_evaluator(kind="CODE")` decorator for each.
>
> 1. `execution_accuracy(output, expected) -> float`:
>    - Takes the generated SQL (from pipeline output) and the golden SQL (from dataset expected)
>    - Executes both against Snowflake
>    - Compares result sets using `datacompy.Compare()`
>    - Returns intersection percentage (0.0 to 1.0)
>    - Handle errors gracefully (connection failures, invalid SQL) — return 0.0, don't crash
>    - Install `datacompy` if not present
>
> 2. `decomposition_coverage(output, expected) -> float`:
>    - Compares actual sub-questions against expected sub-questions
>    - Simple approach: normalize and do token-level set intersection
>    - Returns coverage fraction (0.0 to 1.0)
>
> 3. `key_value_presence(output, expected) -> float`:
>    - Checks if expected key values (from `must_contain` in golden dataset) appear in the final answer text
>    - Returns fraction found (0.0 to 1.0)
>
> 4. `sql_syntax_valid(output) -> bool`:
>    - Same sqlparse check from Tier 1, wrapped as a Phoenix evaluator for experiment scoring
>
> **Important**: The Snowflake connection for `execution_accuracy` needs to be created once and reused. Use our existing connection pattern from the pipeline code. Check `docs/eval_code_mapping.md` for how we currently connect.

---

## Prompt 5: Tier 3 — LLM Evaluators + Experiment Runner

> Create the LLM evaluation layer and the experiment runner for Tier 3 golden dataset testing.
>
> **Create `evaluation/llm_evaluators.py`:**
>
> Set up Phoenix's pre-built LLM eval templates. We use Azure OpenAI — configure the judge model as `gpt-4o-mini` through our existing Azure OpenAI connection.
>
> The evaluators to configure:
> 1. SQL Generation eval (`SQL_GEN_EVAL_PROMPT_TEMPLATE`) — evaluates SQL correctness given the question and execution results
> 2. Hallucination eval (`HALLUCINATION_PROMPT_TEMPLATE`) — evaluates if synthesis is grounded in the data
> 3. QA Correctness eval (`QA_PROMPT_TEMPLATE`) — evaluates if the answer correctly addresses the question
> 4. Summarization eval (`SUMMARIZATION_PROMPT_TEMPLATE`) — evaluates summary quality
> 5. Custom decomposition quality eval — create via `create_classifier()` with a prompt that asks: "Do these sub-questions fully cover the original question? Are any redundant or off-topic?" with choices `{"complete": 1.0, "partial": 0.5, "poor": 0.0}`
>
> **Important context for Tier 3**: These LLM evals have access to ground truth from the golden dataset. When constructing the DataFrames for `llm_classify`, include the golden expected answer as the reference/context column so the judge is comparing against known-correct answers, not just checking internal consistency.
>
> **Create `evaluation/run_experiment.py`:**
>
> A script that:
> 1. Loads the golden dataset from Phoenix
> 2. Defines a `pipeline_task` function that runs each question through the full pipeline
> 3. Runs `run_experiment()` with ALL evaluators (code + LLM) attached
> 4. Names the experiment with a version and description (accept these as CLI args)
>
> Usage: `python evaluation/run_experiment.py --name "v2.1-new-decomp-prompt" --description "Testing chain-of-thought decomposition"`
>
> This is the full regression suite. It should work locally and in CI.

---

## Prompt 6: Tier 2 — Async Production Evaluation

> Create the asynchronous production evaluation layer. This runs AFTER the response has been delivered. It has NO ground truth — it can only check internal consistency across pipeline stages.
>
> **Create `evaluation/async_production_eval.py`:**
>
> A script (designed to run on a schedule — cron, Snowflake Task, or Airflow) that:
>
> 1. Pulls recent traces from Phoenix using `px.Client().get_spans_dataframe()` for the last N hours (configurable, default 1 hour)
>
> 2. Prepares DataFrames for each evaluator by:
>    - Filtering spans by name (decompose, sql_generation_*, summarize, synthesize)
>    - Renaming attributes to match each eval template's expected variables
>    - Joining related spans on trace_id where needed (e.g., joining sql_generation output with sql_execution results to give the SQL gen eval the `{response}` variable)
>
> 3. Runs these LLM evals via `llm_classify()` with `concurrency=20`:
>    - **Decomposition quality** (custom `create_classifier`) — "Do these sub-questions cover the original question?"
>    - **SQL Generation** (pre-built) — "Does this SQL answer the question given the results?"
>    - **Summarization** (pre-built) — "Is this summary comprehensive and coherent?"
>    - **Hallucination** (pre-built) — "Is the synthesis grounded in the summaries and data?"
>    - **QA Correctness** (pre-built) — "Does the answer address the user's question?"
>
> 4. **Critical**: At Tier 2, the judge's context is the pipeline's own outputs, NOT ground truth. When building the DataFrames:
>    - Hallucination eval context = the summaries and SQL results the pipeline produced
>    - QA eval reference = the data the pipeline retrieved, not a known-correct answer
>    - SQL gen eval response = the actual execution results
>    - Document this clearly in code comments so future developers understand the difference from Tier 3
>
> 5. Logs all scores back to Phoenix as span annotations via `client.log_evaluations(SpanEvaluations(...))`
>
> 6. Flags failures for review:
>    - Any trace where hallucination = "hallucinated"
>    - Any trace where SQL gen = "incorrect"
>    - Any trace where QA = "incorrect"
>    - Writes flagged traces to `evaluation/flagged/review_YYYYMMDD.csv`
>
> Usage: `python evaluation/async_production_eval.py --hours 1`
>
> Also explore whether any of these can be attached as Phoenix online evaluations (evaluators that run automatically on incoming traces). If our Phoenix instance supports this, set up hallucination and SQL gen evals as online evals and note which ones still need the batch script.

---

## Prompt 7: CI/CD Quality Gate

> Create the CI/CD pipeline that runs Tier 3 evaluation on pull requests and nightly.
>
> **Create `.github/workflows/eval.yml`:**
>
> Trigger on:
> - Pull requests that change: `prompts/**`, `semantic_model.yaml`, `pipeline/**`, `evaluation/**`
> - Nightly schedule (cron, 2am)
>
> Steps:
> 1. Checkout, setup Python
> 2. Install dependencies (create `requirements-eval.txt` with eval-specific deps)
> 3. Run `evaluation/run_experiment.py` with experiment name derived from PR number or "nightly-YYYYMMDD"
> 4. Run quality gate check
>
> **Create `evaluation/quality_gate.py`:**
>
> Reads the latest experiment results from Phoenix and checks pass rates against thresholds:
>
> ```
> execution_accuracy >= 0.80
> decomposition_coverage >= 0.75
> key_value_presence >= 0.85
> sql_syntax_valid >= 0.95
> SQL Correctness (LLM) >= 0.80
> Hallucination (LLM) >= 0.85
> QA Correctness (LLM) >= 0.80
> Summarization (LLM) >= 0.80
> ```
>
> Exit code 0 if all pass, exit code 1 if any fail. Print clear pass/fail for each metric.
>
> **Environment variables needed** (document these in the workflow):
> - `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`
> - `PHOENIX_API_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`
> - `OPENAI_API_KEY` (or Azure OpenAI equivalent)
>
> Make sure secrets are referenced properly in the GitHub Actions workflow.

---

## Prompt 8: Eval-the-Evals Infrastructure

> Set up the infrastructure for validating that our LLM judges actually agree with human judgment.
>
> **Create `evaluation/eval_the_evals.py`:**
>
> A script that:
> 1. Pulls traces that have BOTH LLM evaluation annotations AND human annotations from Phoenix
> 2. Computes agreement rate between the LLM judge and human labels for each evaluator
> 3. Reports agreement percentage and Cohen's kappa per evaluator
> 4. Flags evaluators with < 80% agreement for prompt tuning
>
> **Create `evaluation/annotation_guide.md`:**
>
> A brief guide for our weekly review process:
> 1. How to pull flagged traces from `evaluation/flagged/`
> 2. How to annotate traces in the Phoenix UI (label as correct/incorrect/partial for each node)
> 3. How to promote confirmed failures to the golden dataset
> 4. How to run `eval_the_evals.py` monthly to check judge calibration
> 5. Recommended: annotate 20-30 traces per weekly review session
>
> Keep this doc short and practical — it's for me (solo developer) and eventually for team onboarding.

---

## After All Prompts

Once all 8 prompts are complete, your repo should have:

```
evaluation/
├── __init__.py
├── inline_checks.py          # Tier 1: hot-path Python checks
├── code_evaluators.py         # Tier 3: deterministic Phoenix evaluators
├── llm_evaluators.py          # Tier 2 & 3: LLM judge config
├── async_production_eval.py   # Tier 2: scheduled batch eval
├── run_experiment.py          # Tier 3: golden dataset experiment runner
├── quality_gate.py            # CI/CD: pass/fail threshold check
├── eval_the_evals.py          # Meta: judge calibration
├── golden_dataset.py          # Dataset structure & upload
├── golden_examples.yaml       # Actual golden examples
├── upload_golden_dataset.py   # Upload script
├── annotation_guide.md        # Weekly review process
├── flagged/                   # Auto-populated by Tier 2
│   └── .gitkeep
tracing.py                     # Phoenix OTEL setup
docs/
├── cortex_analyst_eval_plan_3tier.md  # The plan (reference doc)
├── eval_code_mapping.md               # Generated by Prompt 0
.github/
└── workflows/
    └── eval.yml               # CI/CD pipeline
```

**Verification steps after implementation:**
1. Run the pipeline with tracing — verify all 5 stages appear in Phoenix UI
2. Trigger an inline check failure (send malformed SQL) — verify it's caught
3. Run `upload_golden_dataset.py` — verify dataset appears in Phoenix
4. Run `run_experiment.py` — verify experiment results with all evaluator scores in Phoenix
5. Run `async_production_eval.py` — verify span annotations appear on production traces
6. Open a PR that changes a prompt — verify GitHub Actions runs the eval workflow