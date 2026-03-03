from __future__ import annotations

import pandas as pd
import pytest

from evaluation import llm_evaluators_v2_1 as evals


def _clear_judge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "EVAL_JUDGE_PROVIDER",
        "EVAL_JUDGE_MODEL",
        "EVAL_JUDGE_CLIENT",
        "EVAL_JUDGE_CLIENT_KWARGS_JSON",
        "EVAL_JUDGE_SYNC_CLIENT_KWARGS_JSON",
        "EVAL_JUDGE_ASYNC_CLIENT_KWARGS_JSON",
        "EVAL_JUDGE_OPENAI_API_KEY",
        "EVAL_JUDGE_OPENAI_BASE_URL",
        "EVAL_JUDGE_OPENAI_ORG",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "EVAL_JUDGE_AZURE_API_KEY",
        "EVAL_JUDGE_AZURE_ENDPOINT",
        "EVAL_JUDGE_AZURE_API_VERSION",
        "EVAL_JUDGE_AZURE_BASE_URL",
        "EVAL_JUDGE_AZURE_AD_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_BASE_URL",
        "EVAL_JUDGE_ANTHROPIC_API_KEY",
        "EVAL_JUDGE_ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_judge_config_defaults_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default")

    provider, model, init_kwargs, _, _ = evals._judge_config_from_env(None)

    assert provider == "openai"
    assert model == "gpt-4o-mini"
    assert init_kwargs["provider"] == "openai"
    assert init_kwargs["model"] == "gpt-4o-mini"
    assert init_kwargs["api_key"] == "sk-default"


def test_judge_config_supports_azure_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "azureopenai")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o-mini-deployment")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    provider, model, init_kwargs, _, _ = evals._judge_config_from_env(None)

    assert provider == "azure"
    assert model == "gpt-4o-mini-deployment"
    assert init_kwargs["provider"] == "azure"
    assert init_kwargs["api_key"] == "azure-key"
    assert init_kwargs["azure_endpoint"] == "https://example.openai.azure.com"
    assert init_kwargs["api_version"] == "2024-10-21"


def test_judge_config_supports_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "claude-3-5-sonnet-latest")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    provider, model, init_kwargs, _, _ = evals._judge_config_from_env(None)

    assert provider == "anthropic"
    assert model == "claude-3-5-sonnet-latest"
    assert init_kwargs["provider"] == "anthropic"
    assert init_kwargs["api_key"] == "anthropic-key"


def test_judge_config_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("EVAL_JUDGE_CLIENT_KWARGS_JSON", "[]")

    with pytest.raises(RuntimeError, match="EVAL_JUDGE_CLIENT_KWARGS_JSON must be a JSON object"):
        evals._judge_config_from_env(None)


def test_build_judge_uses_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "azure_openai")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "deployment-name")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    captured: dict[str, str] = {}

    class _FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(evals, "LLM", _FakeLLM)
    monkeypatch.setattr(evals, "_is_legacy_llm_classify", lambda: False)

    judge = evals.build_judge()

    assert judge is not None
    assert captured["provider"] == "azure"
    assert captured["model"] == "deployment-name"
    assert captured["api_key"] == "azure-key"


def test_build_judge_legacy_path_uses_openai_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
    monkeypatch.setattr(evals, "_is_legacy_llm_classify", lambda: True)

    captured: dict[str, str] = {}

    class _FakeOpenAIModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _FakeAnthropicModel:
        def __init__(self, **kwargs):
            raise AssertionError("Anthropic model should not be used for OpenAI provider")

    monkeypatch.setattr("phoenix.evals.OpenAIModel", _FakeOpenAIModel)
    monkeypatch.setattr("phoenix.evals.AnthropicModel", _FakeAnthropicModel)

    judge = evals.build_judge()
    assert judge is not None
    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"] == "sk-key"


def test_classify_decomposition_supports_dataframe_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DataFrameClassifier:
        def evaluate(self, *, dataframe):
            return pd.DataFrame(
                {
                    "score": [1.0],
                    "label": ["complete"],
                    "explanation": ["ok"],
                }
            )

    monkeypatch.setattr(evals, "build_decomposition_classifier", lambda _judge: _DataFrameClassifier())
    monkeypatch.setattr(evals, "_is_legacy_llm_classify", lambda: False)
    df = pd.DataFrame([{"question": "q", "sub_questions": "[]", "context.trace_id": "t1"}])
    result = evals.classify_decomposition(df, judge=object())
    assert isinstance(result, pd.DataFrame)
    assert result.loc[0, "score"] == 1.0
    assert result.loc[0, "label"] == "complete"


def test_classify_decomposition_supports_row_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Score:
        def __init__(self, score: float, label: str, explanation: str):
            self.score = score
            self.label = label
            self.explanation = explanation

    class _RowClassifier:
        def evaluate(self, eval_input, input_mapping=None):
            _ = input_mapping
            assert isinstance(eval_input, dict)
            return [_Score(0.5, "partial", "needs detail")]

    monkeypatch.setattr(evals, "build_decomposition_classifier", lambda _judge: _RowClassifier())
    monkeypatch.setattr(evals, "_is_legacy_llm_classify", lambda: False)
    df = pd.DataFrame([{"question": "q", "sub_questions": "[]", "context.span_id": "s1"}])
    result = evals.classify_decomposition(df, judge=object())
    assert isinstance(result, pd.DataFrame)
    assert result.loc[0, "context.span_id"] == "s1"
    assert result.loc[0, "score"] == 0.5
    assert result.loc[0, "label"] == "partial"


def test_classify_decomposition_legacy_uses_llm_classify(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_llm_classify(*, data, template, rails, model, provide_explanation, concurrency):
        captured["data"] = data
        captured["template"] = template
        captured["rails"] = rails
        captured["model"] = model
        captured["provide_explanation"] = provide_explanation
        captured["concurrency"] = concurrency
        return pd.DataFrame({"label": ["partial"], "score": [0.5]})

    monkeypatch.setattr(evals, "_is_legacy_llm_classify", lambda: True)
    monkeypatch.setattr(evals, "llm_classify", _fake_llm_classify)

    df = pd.DataFrame([{"question": "q", "sub_questions": "[]"}])
    marker = object()
    result = evals.classify_decomposition(df, judge=marker)

    assert isinstance(result, pd.DataFrame)
    assert result.loc[0, "label"] == "partial"
    assert captured["model"] is marker
    assert captured["rails"] == ["complete", "partial", "poor"]


def test_prepare_template_dataframe_maps_aliases() -> None:
    df = pd.DataFrame([{"input": "q", "output": "a", "context": "ctx"}])
    out = evals._prepare_template_dataframe(
        df,
        template="Q={input} R={reference} A={output}",
        aliases={"reference": ["context"]},
    )
    assert set(out.columns) == {"input", "output", "reference"}
    assert out.iloc[0]["reference"] == "ctx"
