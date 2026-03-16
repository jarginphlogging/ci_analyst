# Annotation Guide

## Weekly Loop

1. Run async production eval:

```bash
python -m evaluation.async_production_eval --hours 24
```

2. Open latest flagged file:

- `evaluation/flagged/review_YYYYMMDD.csv`

3. Open Phoenix UI and review traces:

- Project: `cortex-analyst-pipeline`
- Filter spans by `pipeline.t1_plan`, `pipeline.t2_sql`, and `pipeline.t4_synthesis*`
- Open each trace from the flagged CSV by `context.span_id`/`context.trace_id`

4. For each flagged trace, label stage outcomes in Phoenix annotations:

- `correct`
- `partial`
- `incorrect`

Label definitions:

- `correct`: output is fully aligned with the stage input/contract and does not require remediation.
- `partial`: output is directionally useful but incomplete, imprecise, or weakly justified.
- `incorrect`: output is wrong, unsupported, policy-violating, or unusable.

Stage targets:

- `t1` plan quality
- `t2` SQL quality
- `t4` answer groundedness and correctness

5. Promote confirmed failures to golden dataset:

- append new case to `evaluation/golden_examples.yaml`
- upload dataset:

```bash
python -m evaluation.upload_golden_dataset
```

## Monthly Calibration

Run:

```bash
python -m evaluation.eval_the_evals --min-agreement 0.80
```

If agreement is below threshold for any evaluator:

1. review false positive/false negative examples
2. tighten prompt rails for that evaluator
3. re-run async eval and calibration
