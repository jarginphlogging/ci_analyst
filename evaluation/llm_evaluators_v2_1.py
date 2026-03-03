from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from phoenix.evals import (
        HALLUCINATION_PROMPT_RAILS_MAP,
        HALLUCINATION_PROMPT_TEMPLATE,
        QA_PROMPT_RAILS_MAP,
        QA_PROMPT_TEMPLATE,
        SQL_GEN_EVAL_PROMPT_RAILS_MAP,
        SQL_GEN_EVAL_PROMPT_TEMPLATE,
        SUMMARIZATION_PROMPT_RAILS_MAP,
        SUMMARIZATION_PROMPT_TEMPLATE,
        LLM,
        create_classifier,
        llm_classify,
    )
except Exception:  # noqa: BLE001
    HALLUCINATION_PROMPT_TEMPLATE = "Input: {input}\nContext: {context}\nOutput: {output}\nLabel hallucinated or grounded."
    QA_PROMPT_TEMPLATE = "Query: {query}\nReference: {reference}\nAnswer: {sampled_answer}\nLabel correct or incorrect."
    SQL_GEN_EVAL_PROMPT_TEMPLATE = (
        "Question: {question}\nSQL: {query_gen}\nExecution response: {response}\nLabel correct or incorrect."
    )
    SUMMARIZATION_PROMPT_TEMPLATE = "Input: {input}\nSummary: {output}\nLabel good or bad."
    HALLUCINATION_PROMPT_RAILS_MAP = {}
    QA_PROMPT_RAILS_MAP = {}
    SQL_GEN_EVAL_PROMPT_RAILS_MAP = {}
    SUMMARIZATION_PROMPT_RAILS_MAP = {}
    LLM = None  # type: ignore[assignment]
    create_classifier = None  # type: ignore[assignment]
    llm_classify = None  # type: ignore[assignment]


def build_judge(model_name: str = "gpt-4o-mini") -> Any:
    if LLM is None:
        raise RuntimeError("Phoenix eval LLM dependency is unavailable.")
    return LLM(provider="openai", model=model_name)


def build_decomposition_classifier(judge: Any) -> Any:
    if create_classifier is None:
        raise RuntimeError("Phoenix create_classifier is unavailable.")
    return create_classifier(
        name="decomposition_quality",
        prompt_template=(
            "Question: {question}\n"
            "Plan: {sub_questions}\n"
            "Do these steps fully cover the user intent? Are any redundant or off-topic?"
        ),
        llm=judge,
        choices={"complete": 1.0, "partial": 0.5, "poor": 0.0},
    )


def classify_sql_generation(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    return llm_classify(
        dataframe=dataframe,
        template=SQL_GEN_EVAL_PROMPT_TEMPLATE,
        model=judge,
        rails=list(SQL_GEN_EVAL_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_hallucination(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    return llm_classify(
        dataframe=dataframe,
        template=HALLUCINATION_PROMPT_TEMPLATE,
        model=judge,
        rails=list(HALLUCINATION_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_qa(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    return llm_classify(
        dataframe=dataframe,
        template=QA_PROMPT_TEMPLATE,
        model=judge,
        rails=list(QA_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_synthesis_quality(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    return llm_classify(
        dataframe=dataframe,
        template=SUMMARIZATION_PROMPT_TEMPLATE,
        model=judge,
        rails=list(SUMMARIZATION_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )

