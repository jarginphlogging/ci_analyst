from __future__ import annotations

from app.config import settings
from app.providers.anthropic_bedrock import chat_completion as anthropic_bedrock_chat_completion
from app.providers.anthropic_llm import chat_completion as anthropic_direct_chat_completion
from app.providers.azure_openai import chat_completion as azure_chat_completion
from app.providers.protocols import LlmFn


def _requested_llm_provider_for_mode(resolved_mode: str) -> str:
    raw = (settings.llm_provider_raw or "").strip().lower().replace("-", "_")
    if not raw:
        if resolved_mode == "sandbox":
            return "anthropic_direct"
        raise RuntimeError(
            "LLM_PROVIDER must be set for prod and prod-sandbox. "
            "Use one of: azure_openai, anthropic_bedrock."
        )
    if raw in {"azure_openai", "anthropic_bedrock", "anthropic_direct"}:
        return raw
    raise RuntimeError(
        f"Unsupported LLM_PROVIDER '{settings.llm_provider_raw}'. "
        "Use one of: azure_openai, anthropic_bedrock, anthropic_direct."
    )


def resolve_llm_provider(mode: str | None = None) -> tuple[str, LlmFn]:
    resolved_mode = (mode or settings.provider_mode).strip().lower()
    provider = _requested_llm_provider_for_mode(resolved_mode)

    if resolved_mode == "sandbox":
        if provider != "anthropic_direct":
            raise RuntimeError(
                "sandbox mode only supports LLM_PROVIDER=anthropic_direct."
            )
        return provider, anthropic_direct_chat_completion

    if resolved_mode in {"prod", "prod-sandbox"}:
        if provider == "azure_openai":
            return provider, azure_chat_completion
        if provider == "anthropic_bedrock":
            return provider, anthropic_bedrock_chat_completion
        raise RuntimeError(
            f"{resolved_mode} mode does not support LLM_PROVIDER={provider}. "
            "Use azure_openai or anthropic_bedrock."
        )

    raise RuntimeError(f"Unsupported provider mode for LLM routing: {resolved_mode}")
