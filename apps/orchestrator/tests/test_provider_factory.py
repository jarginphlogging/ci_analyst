from __future__ import annotations

import pytest

from app.providers.factory import build_provider_bundle


def test_build_provider_bundle_for_prod() -> None:
    bundle = build_provider_bundle("prod")
    assert bundle.llm_fn
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_for_prod_sandbox() -> None:
    bundle = build_provider_bundle("prod-sandbox")
    assert bundle.llm_fn
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_for_sandbox() -> None:
    bundle = build_provider_bundle("sandbox")
    assert bundle.llm_fn
    assert bundle.sql_fn
    assert bundle.analyst_fn


def test_build_provider_bundle_rejects_unknown_mode() -> None:
    with pytest.raises(RuntimeError):
        build_provider_bundle("invalid")
