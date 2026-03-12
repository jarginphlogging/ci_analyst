from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from openai import AsyncAzureOpenAI

from app.config import settings
from app.providers.azure_schema import compile_azure_strict_schema

_TOKEN_CACHE: dict[str, int | str | None] = {"token": None, "expires_on": 0}
_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
logger = logging.getLogger(__name__)


def _require_azure_settings() -> None:
    if not settings.has_azure_credentials():
        raise RuntimeError(
            "Azure OpenAI credentials are not configured. Set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_DEPLOYMENT or AZURE_OPENAI_MODEL, plus auth-mode-specific credentials."
        )


def _resolve_certificate_path(cert_path_raw: str) -> Path:
    candidate = Path(cert_path_raw).expanduser()
    if candidate.is_absolute():
        return candidate

    search_roots = (Path.cwd(), _ORCHESTRATOR_ROOT, _REPO_ROOT)
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return candidate.resolve()


def _get_certificate_token() -> str:
    cached_token = _TOKEN_CACHE.get("token")
    cached_expiry = int(_TOKEN_CACHE.get("expires_on") or 0)
    if isinstance(cached_token, str) and cached_token and (cached_expiry - int(time.time()) > 120):
        return cached_token

    try:
        from azure.identity import CertificateCredential
    except ImportError as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError(
            "azure-identity is required for AZURE_OPENAI_AUTH_MODE=certificate. "
            "Install it with `python -m pip install azure-identity`."
        ) from exc

    cert_path_raw = settings.azure_spn_cert_path
    if not cert_path_raw:
        raise RuntimeError("AZURE_SPN_CERT_PATH is required for certificate auth mode.")

    cert_path = _resolve_certificate_path(cert_path_raw)
    if not cert_path.exists():
        raise RuntimeError(f"Certificate file not found at {cert_path}")

    credential = CertificateCredential(
        tenant_id=str(settings.azure_tenant_id),
        client_id=str(settings.azure_spn_client_id),
        certificate_data=cert_path.read_bytes(),
        password=settings.azure_spn_cert_password,
    )
    access_token = credential.get_token(settings.azure_openai_scope)

    _TOKEN_CACHE["token"] = access_token.token
    _TOKEN_CACHE["expires_on"] = int(access_token.expires_on)
    return access_token.token


def _client_api_key() -> str:
    if settings.azure_openai_auth_mode == "certificate":
        return _get_certificate_token()

    api_key = settings.azure_openai_api_key
    if not api_key:
        raise RuntimeError("AZURE_OPENAI_API_KEY is required for AZURE_OPENAI_AUTH_MODE=api_key.")
    return api_key


def _default_headers() -> dict[str, str] | None:
    gateway_key = settings.azure_openai_gateway_api_key
    if not gateway_key:
        return None
    return {settings.azure_openai_gateway_api_key_header: gateway_key}


def _build_client() -> AsyncAzureOpenAI:
    _require_azure_settings()
    client_kwargs: dict[str, Any] = {
        "azure_endpoint": str(settings.azure_openai_endpoint),
        "api_version": settings.azure_openai_api_version,
        "api_key": _client_api_key(),
        "timeout": 30.0,
    }
    default_headers = _default_headers()
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    return AsyncAzureOpenAI(**client_kwargs)


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    response_json: bool = False,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
) -> str:
    if response_json and response_schema is not None:
        raise RuntimeError("response_json and response_schema cannot be combined.")

    payload: dict[str, Any] = {
        "model": str(settings.azure_openai_deployment),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }

    if response_schema is not None:
        azure_schema = compile_azure_strict_schema(response_schema)
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": (response_schema_name or "structured_response").strip() or "structured_response",
                "strict": True,
                "schema": azure_schema,
            },
        }
    elif response_json:
        payload["response_format"] = {"type": "json_object"}

    started_at = time.perf_counter()
    logger.info(
        "Azure OpenAI request started",
        extra={
            "event": "provider.azure_openai.request.started",
            "authMode": settings.azure_openai_auth_mode,
            "responseJson": response_json,
            "responseSchema": response_schema is not None,
            "maxTokens": max_tokens,
            "temperature": temperature,
            "systemPromptChars": len(system_prompt),
            "userPromptChars": len(user_prompt),
        },
    )

    try:
        client = _build_client()
        response = await client.chat.completions.create(**payload)
    except Exception:
        logger.exception(
            "Azure OpenAI request failed before response",
            extra={
                "event": "provider.azure_openai.request.failed_transport",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        raise
    finally:
        if "client" in locals():
            await client.close()

    choices = list(getattr(response, "choices", []) or [])
    if not choices:
        logger.info(
            "Azure OpenAI request completed with empty choices",
            extra={
                "event": "provider.azure_openai.request.completed",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
                "choices": 0,
            },
        )
        return ""

    logger.info(
        "Azure OpenAI request completed",
        extra={
            "event": "provider.azure_openai.request.completed",
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
            "choices": len(choices),
        },
    )

    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            text_value = getattr(part, "text", None)
            if isinstance(text_value, str):
                text_parts.append(text_value)
                continue
            if isinstance(part, dict):
                dict_text = part.get("text")
                if isinstance(dict_text, str):
                    text_parts.append(dict_text)
        return "".join(text_parts)
    return str(content)


async def complete_with_azure(task: str, user_message: str, *, context: Optional[str] = None) -> str:
    system_prompt = f"You are the {task} component. Return concise structured output."
    if context:
        system_prompt = f"{system_prompt}\n\nContext:\n{context}"
    return await chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_message,
        temperature=0.2,
        max_tokens=400,
    )
