from __future__ import annotations

from dataclasses import dataclass

from app.providers.azure_openai import chat_completion
from app.providers.protocols import LlmFn, SqlFn
from app.providers.snowflake_cortex import execute_cortex_sql


@dataclass(frozen=True)
class ProviderBundle:
    llm_fn: LlmFn
    sql_fn: SqlFn


def build_live_provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm_fn=chat_completion,
        sql_fn=execute_cortex_sql,
    )
