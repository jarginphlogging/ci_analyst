from __future__ import annotations

import json
import os
import re
from typing import Any

import pandas as pd

HALLUCINATION_PROMPT_TEMPLATE = "Input: {input}\nContext: {context}\nOutput: {output}\nLabel hallucinated or grounded."
QA_PROMPT_TEMPLATE = "Query: {query}\nReference: {reference}\nAnswer: {sampled_answer}\nLabel correct or incorrect."
SQL_GEN_EVAL_PROMPT_TEMPLATE = (
    "Question: {question}\nSQL: {query_gen}\nExecution response: {response}\nLabel correct or incorrect."
)
SUMMARIZATION_PROMPT_TEMPLATE = "Input: {input}\nSummary: {output}\nLabel good or bad."
HALLUCINATION_PROMPT_RAILS_MAP: dict[str, Any] = {}
QA_PROMPT_RAILS_MAP: dict[str, Any] = {}
SQL_GEN_EVAL_PROMPT_RAILS_MAP: dict[str, Any] = {}
SUMMARIZATION_PROMPT_RAILS_MAP: dict[str, Any] = {}
LLM = None  # type: ignore[assignment]
create_classifier = None  # type: ignore[assignment]
llm_classify = None  # type: ignore[assignment]
adapter_availability_table = None  # type: ignore[assignment]

try:
    import phoenix.evals as _phoenix_evals

    HALLUCINATION_PROMPT_TEMPLATE = getattr(
        _phoenix_evals,
        "HALLUCINATION_PROMPT_TEMPLATE",
        HALLUCINATION_PROMPT_TEMPLATE,
    )
    QA_PROMPT_TEMPLATE = getattr(_phoenix_evals, "QA_PROMPT_TEMPLATE", QA_PROMPT_TEMPLATE)
    SQL_GEN_EVAL_PROMPT_TEMPLATE = getattr(
        _phoenix_evals,
        "SQL_GEN_EVAL_PROMPT_TEMPLATE",
        SQL_GEN_EVAL_PROMPT_TEMPLATE,
    )
    SUMMARIZATION_PROMPT_TEMPLATE = getattr(
        _phoenix_evals,
        "SUMMARIZATION_PROMPT_TEMPLATE",
        SUMMARIZATION_PROMPT_TEMPLATE,
    )
    HALLUCINATION_PROMPT_RAILS_MAP = getattr(
        _phoenix_evals,
        "HALLUCINATION_PROMPT_RAILS_MAP",
        HALLUCINATION_PROMPT_RAILS_MAP,
    )
    QA_PROMPT_RAILS_MAP = getattr(
        _phoenix_evals,
        "QA_PROMPT_RAILS_MAP",
        QA_PROMPT_RAILS_MAP,
    )
    SQL_GEN_EVAL_PROMPT_RAILS_MAP = getattr(
        _phoenix_evals,
        "SQL_GEN_EVAL_PROMPT_RAILS_MAP",
        SQL_GEN_EVAL_PROMPT_RAILS_MAP,
    )
    SUMMARIZATION_PROMPT_RAILS_MAP = getattr(
        _phoenix_evals,
        "SUMMARIZATION_PROMPT_RAILS_MAP",
        SUMMARIZATION_PROMPT_RAILS_MAP,
    )
    LLM = getattr(_phoenix_evals, "LLM", None)
    create_classifier = getattr(_phoenix_evals, "create_classifier", None)
    llm_classify = getattr(_phoenix_evals, "llm_classify", None)
except Exception:  # noqa: BLE001
    pass

try:
    from phoenix.evals.llm.registries import adapter_availability_table
except Exception:  # noqa: BLE001
    adapter_availability_table = None  # type: ignore[assignment]


def _as_optional(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


def _provider_alias(raw: str | None) -> str:
    value = (raw or "openai").strip().lower()
    aliases = {
        "azureopenai": "azure",
        "azure_openai": "azure",
        "azure-openai": "azure",
    }
    return aliases.get(value, value)


def _template_vars(template: Any) -> set[str]:
    if hasattr(template, "variables"):
        variables = getattr(template, "variables")
        if isinstance(variables, list):
            return {str(item) for item in variables if str(item).strip()}
    text = template if isinstance(template, str) else str(template or "")
    return set(re.findall(r"{([a-zA-Z_][a-zA-Z0-9_]*)}", text))


def _prepare_template_dataframe(
    dataframe: pd.DataFrame,
    *,
    template: Any,
    aliases: dict[str, list[str]],
) -> pd.DataFrame:
    required = _template_vars(template)
    if not required:
        return dataframe.copy()

    out = dataframe.copy()
    for name in required:
        if name in out.columns:
            continue
        for source in aliases.get(name, []):
            if source in out.columns:
                out[name] = out[source]
                break
        else:
            out[name] = ""

    for name in required:
        series = out[name].fillna("").astype(str).str.strip()
        out[name] = series.replace({"nan": "", "None": "", "null": ""})
    return out[list(required)]


def _parse_json_dict(raw: str | None, *, env_name: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{env_name} must be valid JSON object: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name} must be a JSON object.")
    return value


def _merge_nonempty(base: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    merged = dict(base)
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


def _judge_config_from_env(model_name: str | None) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    provider = _provider_alias(os.getenv("EVAL_JUDGE_PROVIDER"))
    model = _as_optional(model_name) or _as_optional(os.getenv("EVAL_JUDGE_MODEL")) or "gpt-4o-mini"
    client = _as_optional(os.getenv("EVAL_JUDGE_CLIENT"))

    common_kwargs = _parse_json_dict(
        os.getenv("EVAL_JUDGE_CLIENT_KWARGS_JSON"),
        env_name="EVAL_JUDGE_CLIENT_KWARGS_JSON",
    )
    sync_kwargs = _parse_json_dict(
        os.getenv("EVAL_JUDGE_SYNC_CLIENT_KWARGS_JSON"),
        env_name="EVAL_JUDGE_SYNC_CLIENT_KWARGS_JSON",
    )
    async_kwargs = _parse_json_dict(
        os.getenv("EVAL_JUDGE_ASYNC_CLIENT_KWARGS_JSON"),
        env_name="EVAL_JUDGE_ASYNC_CLIENT_KWARGS_JSON",
    )

    if provider == "openai":
        common_kwargs = _merge_nonempty(
            common_kwargs,
            api_key=_as_optional(os.getenv("EVAL_JUDGE_OPENAI_API_KEY")) or _as_optional(os.getenv("OPENAI_API_KEY")),
            base_url=_as_optional(os.getenv("EVAL_JUDGE_OPENAI_BASE_URL")) or _as_optional(os.getenv("OPENAI_BASE_URL")),
            organization=_as_optional(os.getenv("EVAL_JUDGE_OPENAI_ORG"))
            or _as_optional(os.getenv("OPENAI_ORG_ID")),
        )
    elif provider == "azure":
        common_kwargs = _merge_nonempty(
            common_kwargs,
            api_key=_as_optional(os.getenv("EVAL_JUDGE_AZURE_API_KEY"))
            or _as_optional(os.getenv("AZURE_OPENAI_API_KEY")),
            azure_endpoint=_as_optional(os.getenv("EVAL_JUDGE_AZURE_ENDPOINT"))
            or _as_optional(os.getenv("AZURE_OPENAI_ENDPOINT")),
            api_version=_as_optional(os.getenv("EVAL_JUDGE_AZURE_API_VERSION"))
            or _as_optional(os.getenv("AZURE_OPENAI_API_VERSION")),
            base_url=_as_optional(os.getenv("EVAL_JUDGE_AZURE_BASE_URL"))
            or _as_optional(os.getenv("AZURE_OPENAI_BASE_URL")),
            azure_ad_token=_as_optional(os.getenv("EVAL_JUDGE_AZURE_AD_TOKEN")),
        )
    elif provider == "anthropic":
        common_kwargs = _merge_nonempty(
            common_kwargs,
            api_key=_as_optional(os.getenv("EVAL_JUDGE_ANTHROPIC_API_KEY"))
            or _as_optional(os.getenv("ANTHROPIC_API_KEY")),
            base_url=_as_optional(os.getenv("EVAL_JUDGE_ANTHROPIC_BASE_URL"))
            or _as_optional(os.getenv("ANTHROPIC_BASE_URL")),
        )

    init_kwargs: dict[str, Any] = {"provider": provider, "model": model}
    if client:
        init_kwargs["client"] = client
    if common_kwargs:
        init_kwargs.update(common_kwargs)
    if sync_kwargs:
        init_kwargs["sync_client_kwargs"] = sync_kwargs
    if async_kwargs:
        init_kwargs["async_client_kwargs"] = async_kwargs
    return provider, model, init_kwargs, sync_kwargs, async_kwargs


def _is_legacy_llm_classify() -> bool:
    module_name = getattr(llm_classify, "__module__", "")
    return isinstance(module_name, str) and ".legacy." in module_name


def _build_legacy_judge(provider: str, model: str, init_kwargs: dict[str, Any]) -> Any:
    try:
        from phoenix.evals import AnthropicModel, OpenAIModel
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Legacy Phoenix eval model dependencies are unavailable.") from error

    common = dict(init_kwargs)
    common.pop("provider", None)
    common.pop("model", None)
    common.pop("client", None)
    common.pop("sync_client_kwargs", None)
    common.pop("async_client_kwargs", None)

    if provider == "openai":
        return OpenAIModel(
            model=model,
            api_key=common.get("api_key"),
            base_url=common.get("base_url"),
            organization=common.get("organization"),
        )
    if provider == "azure":
        azure_deployment = _as_optional(os.getenv("EVAL_JUDGE_AZURE_DEPLOYMENT")) or model
        return OpenAIModel(
            model=model,
            api_key=common.get("api_key"),
            azure_endpoint=common.get("azure_endpoint"),
            api_version=common.get("api_version"),
            azure_ad_token=common.get("azure_ad_token"),
            azure_deployment=azure_deployment,
            base_url=common.get("base_url"),
        )
    if provider == "anthropic":
        api_key = common.get("api_key")
        if api_key and not os.getenv("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = str(api_key)
        base_url = common.get("base_url")
        if base_url and not os.getenv("ANTHROPIC_BASE_URL"):
            os.environ["ANTHROPIC_BASE_URL"] = str(base_url)
        # Some newer Anthropic models reject sending both temperature and top_p.
        return AnthropicModel(model=model, top_p=None)
    raise RuntimeError(
        "Legacy Phoenix llm_classify supports openai/azure/anthropic in this evaluator setup. "
        f"Received provider={provider}."
    )


def build_judge(model_name: str | None = None) -> Any:
    if LLM is None:
        raise RuntimeError("Phoenix eval LLM dependency is unavailable.")
    provider, model, init_kwargs, _sync_kwargs, _async_kwargs = _judge_config_from_env(model_name)
    try:
        if _is_legacy_llm_classify():
            return _build_legacy_judge(provider, model, init_kwargs)
        return LLM(**init_kwargs)
    except Exception as error:  # noqa: BLE001
        availability = adapter_availability_table() if callable(adapter_availability_table) else ""
        raise RuntimeError(
            "Failed to initialize Phoenix eval judge "
            f"(provider={provider}, model={model}). "
            "Check EVAL_JUDGE_* environment variables and provider SDK dependencies.\n"
            f"{availability}\n"
            f"Underlying error: {error}"
        ) from error


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


def classify_decomposition(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if _is_legacy_llm_classify():
        if llm_classify is None:
            raise RuntimeError("Phoenix llm_classify is unavailable.")
        return llm_classify(
            data=dataframe,
            template=(
                "Question: {question}\n"
                "Plan: {sub_questions}\n"
                "Do these steps fully cover the user intent? Are any redundant or off-topic?"
            ),
            rails=["complete", "partial", "poor"],
            model=judge,
            provide_explanation=True,
            concurrency=20,
        )

    classifier = build_decomposition_classifier(judge)
    try:
        results = classifier.evaluate(dataframe=dataframe)
        if isinstance(results, pd.DataFrame):
            return results
    except TypeError:
        pass

    rows: list[dict[str, Any]] = []
    for _, series in dataframe.iterrows():
        payload = series.to_dict()
        scores = classifier.evaluate(payload)
        first = scores[0] if isinstance(scores, list) and scores else None
        row: dict[str, Any] = {}
        for context_key in ("context.span_id", "context.trace_id"):
            if context_key in payload:
                row[context_key] = str(payload.get(context_key) or "")
        if first is not None:
            row["score"] = float(getattr(first, "score", 0.0) or 0.0)
            if getattr(first, "label", None) is not None:
                row["label"] = str(getattr(first, "label"))
            if getattr(first, "explanation", None) is not None:
                row["explanation"] = str(getattr(first, "explanation"))
        else:
            row["score"] = 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def classify_sql_generation(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    llm_df = _prepare_template_dataframe(
        dataframe,
        template=SQL_GEN_EVAL_PROMPT_TEMPLATE,
        aliases={
            "input": ["question"],
            "output": ["response"],
            "reference": ["response"],
            "query": ["question"],
            "sampled_answer": ["response"],
            "query_gen": ["query_gen"],
            "question": ["question"],
            "response": ["response"],
        },
    )
    return llm_classify(
        data=llm_df,
        template=SQL_GEN_EVAL_PROMPT_TEMPLATE,
        model=judge,
        rails=list(SQL_GEN_EVAL_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_hallucination(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    llm_df = _prepare_template_dataframe(
        dataframe,
        template=HALLUCINATION_PROMPT_TEMPLATE,
        aliases={
            "reference": ["context", "input"],
            "context": ["context", "input"],
            "input": ["input"],
            "output": ["output"],
            "query": ["input"],
        },
    )
    return llm_classify(
        data=llm_df,
        template=HALLUCINATION_PROMPT_TEMPLATE,
        model=judge,
        rails=list(HALLUCINATION_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_qa(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    llm_df = _prepare_template_dataframe(
        dataframe,
        template=QA_PROMPT_TEMPLATE,
        aliases={
            "input": ["query"],
            "output": ["sampled_answer"],
            "reference": ["reference"],
            "query": ["query"],
            "sampled_answer": ["sampled_answer"],
        },
    )
    return llm_classify(
        data=llm_df,
        template=QA_PROMPT_TEMPLATE,
        model=judge,
        rails=list(QA_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )


def classify_synthesis_quality(dataframe: pd.DataFrame, judge: Any) -> pd.DataFrame:
    if llm_classify is None:
        raise RuntimeError("Phoenix llm_classify is unavailable.")
    llm_df = _prepare_template_dataframe(
        dataframe,
        template=SUMMARIZATION_PROMPT_TEMPLATE,
        aliases={
            "input": ["input"],
            "output": ["output"],
            "reference": ["input"],
            "query": ["input"],
            "sampled_answer": ["output"],
        },
    )
    return llm_classify(
        data=llm_df,
        template=SUMMARIZATION_PROMPT_TEMPLATE,
        model=judge,
        rails=list(SUMMARIZATION_PROMPT_RAILS_MAP.values()),
        provide_explanation=True,
        concurrency=20,
    )
