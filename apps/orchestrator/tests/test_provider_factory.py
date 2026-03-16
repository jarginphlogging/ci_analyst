from __future__ import annotations

import pytest

from app.providers.factory import build_provider_bundle
from app.providers.azure_openai import chat_completion as azure_chat_completion
from app.providers.anthropic_bedrock import chat_completion as bedrock_chat_completion
from app.providers.anthropic_llm import chat_completion as anthropic_direct_chat_completion
from app.config import settings


def test_build_provider_bundle_for_prod() -> None:
    original_llm_provider = settings.llm_provider_raw
    try:
        object.__setattr__(settings, "llm_provider_raw", "azure_openai")
        bundle = build_provider_bundle("prod")
    finally:
        object.__setattr__(settings, "llm_provider_raw", original_llm_provider)

    assert bundle.llm_fn is azure_chat_completion
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_for_prod_sandbox() -> None:
    original_llm_provider = settings.llm_provider_raw
    try:
        object.__setattr__(settings, "llm_provider_raw", "anthropic_bedrock")
        bundle = build_provider_bundle("prod-sandbox")
    finally:
        object.__setattr__(settings, "llm_provider_raw", original_llm_provider)

    assert bundle.llm_fn is bedrock_chat_completion
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_for_sandbox() -> None:
    bundle = build_provider_bundle("sandbox")
    assert bundle.llm_fn is anthropic_direct_chat_completion
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_rejects_missing_llm_provider_in_prod() -> None:
    original_llm_provider = settings.llm_provider_raw
    original_provider_mode = settings.provider_mode_raw
    try:
        object.__setattr__(settings, "provider_mode_raw", "prod")
        object.__setattr__(settings, "llm_provider_raw", None)
        with pytest.raises(RuntimeError, match="LLM_PROVIDER must be set"):
            build_provider_bundle("prod")
    finally:
        object.__setattr__(settings, "llm_provider_raw", original_llm_provider)
        object.__setattr__(settings, "provider_mode_raw", original_provider_mode)


def test_build_provider_bundle_rejects_unknown_mode() -> None:
    with pytest.raises(RuntimeError):
        build_provider_bundle("invalid")
