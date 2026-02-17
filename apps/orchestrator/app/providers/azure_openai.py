from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import settings

_TOKEN_CACHE: dict[str, int | str | None] = {"token": None, "expires_on": 0}


def _chat_endpoint() -> str:
    if not settings.has_azure_credentials():
        raise RuntimeError(
            "Azure OpenAI credentials are not configured. Set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_DEPLOYMENT, plus auth-mode-specific credentials."
        )

    return (
        f"{settings.azure_openai_endpoint}/openai/deployments/{settings.azure_openai_deployment}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )


def _get_certificate_token() -> str:
    cached_token = _TOKEN_CACHE.get("token")
    cached_expiry = int(_TOKEN_CACHE.get("expires_on") or 0)
    # Refresh a little early to avoid mid-request expiration.
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

    cert_path = Path(cert_path_raw).expanduser()
    if not cert_path.exists():
        raise RuntimeError(f"Certificate file not found at {cert_path}")

    cert_bytes = cert_path.read_bytes()

    credential = CertificateCredential(
        tenant_id=str(settings.azure_tenant_id),
        client_id=str(settings.azure_spn_client_id),
        certificate_data=cert_bytes,
        password=settings.azure_spn_cert_password,
    )
    access_token = credential.get_token(settings.azure_openai_scope)

    _TOKEN_CACHE["token"] = access_token.token
    _TOKEN_CACHE["expires_on"] = int(access_token.expires_on)
    return access_token.token


def _auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if settings.azure_openai_auth_mode == "certificate":
        token = _get_certificate_token()
        headers["Authorization"] = f"Bearer {token}"
    else:
        api_key = settings.azure_openai_api_key
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is required for AZURE_OPENAI_AUTH_MODE=api_key.")
        headers["api-key"] = api_key

    gateway_key = settings.azure_openai_gateway_api_key
    if gateway_key:
        headers[settings.azure_openai_gateway_api_key_header] = gateway_key

    return headers


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    response_json: bool = False,
) -> str:
    endpoint = _chat_endpoint()
    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if response_json:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            endpoint,
            headers=_auth_headers(),
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Azure OpenAI request failed ({response.status_code}): {response.text}")

    body = response.json()
    choices = body.get("choices", [])
    if not choices:
        return ""

    return str(choices[0].get("message", {}).get("content", ""))


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
