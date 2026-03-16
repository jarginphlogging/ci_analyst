from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.providers.llm_router import resolve_llm_provider
from app.providers.protocols import AnalystFn, LlmFn, SqlFn
from app.providers.sandbox_cortex import analyze_message, execute_sandbox_sql
from app.providers.snowflake_analyst import analyze_message as analyze_snowflake_analyst_message
from app.providers.snowflake_connector_sql import execute_snowflake_sql


@dataclass(frozen=True)
class ProviderBundle:
    llm_fn: LlmFn
    sql_fn: SqlFn
    analyst_fn: AnalystFn | None = None


def build_live_provider_bundle() -> ProviderBundle:
    _, llm_fn = resolve_llm_provider("prod")
    return ProviderBundle(
        llm_fn=llm_fn,
        sql_fn=execute_snowflake_sql,
        analyst_fn=analyze_snowflake_analyst_message,
    )


def build_prod_sandbox_provider_bundle() -> ProviderBundle:
    _, llm_fn = resolve_llm_provider("prod-sandbox")
    return ProviderBundle(
        llm_fn=llm_fn,
        sql_fn=execute_sandbox_sql,
        analyst_fn=analyze_message,
    )


def build_sandbox_provider_bundle() -> ProviderBundle:
    _, llm_fn = resolve_llm_provider("sandbox")
    return ProviderBundle(
        llm_fn=llm_fn,
        sql_fn=execute_sandbox_sql,
        analyst_fn=analyze_message,
    )


def build_provider_bundle(mode: str | None = None) -> ProviderBundle:
    resolved_mode = (mode or settings.provider_mode).strip().lower()
    if resolved_mode == "prod":
        return build_live_provider_bundle()
    if resolved_mode == "prod-sandbox":
        return build_prod_sandbox_provider_bundle()
    if resolved_mode == "sandbox":
        return build_sandbox_provider_bundle()
    raise RuntimeError(f"Unsupported provider mode for real dependencies: {resolved_mode}")
