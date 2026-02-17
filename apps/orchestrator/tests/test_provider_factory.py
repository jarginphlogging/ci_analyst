from __future__ import annotations

import pytest

from app.providers.factory import build_provider_bundle


def test_build_provider_bundle_for_prod() -> None:
    bundle = build_provider_bundle("prod")
    assert bundle.llm_fn
    assert bundle.sql_fn


def test_build_provider_bundle_for_sandbox() -> None:
    bundle = build_provider_bundle("sandbox")
    assert bundle.llm_fn
    assert bundle.sql_fn


def test_build_provider_bundle_rejects_mock_mode() -> None:
    with pytest.raises(RuntimeError):
        build_provider_bundle("mock")
