from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.providers.anthropic_llm import chat_completion as anthropic_chat_completion
from app.providers.azure_openai import chat_completion
from app.providers.protocols import AnalystFn, LlmFn, SqlFn
from app.providers.sandbox_cortex import analyze_message, execute_sandbox_sql
from app.providers.snowflake_cortex import execute_cortex_sql


@dataclass(frozen=True)
class ProviderBundle:
    llm_fn: LlmFn
    sql_fn: SqlFn
    analyst_fn: AnalystFn | None = None


def build_live_provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm_fn=chat_completion,
        sql_fn=execute_cortex_sql,
        analyst_fn=None,
    )


def build_sandbox_provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm_fn=anthropic_chat_completion,
        sql_fn=execute_sandbox_sql,
        analyst_fn=analyze_message,
    )


def build_provider_bundle(mode: str | None = None) -> ProviderBundle:
    resolved_mode = (mode or settings.provider_mode).strip().lower()
    if resolved_mode == "prod":
        return build_live_provider_bundle()
    if resolved_mode == "sandbox":
        return build_sandbox_provider_bundle()
    raise RuntimeError(f"Unsupported provider mode for real dependencies: {resolved_mode}")
