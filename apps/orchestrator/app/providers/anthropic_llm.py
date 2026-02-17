from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


def _messages_endpoint() -> str:
    if not settings.has_anthropic_credentials():
        raise RuntimeError(
            "Anthropic credentials are not configured. Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL."
        )
    return f"{settings.anthropic_base_url.rstrip('/')}/v1/messages"


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    response_json: bool = False,
) -> str:
    endpoint = _messages_endpoint()
    effective_system = system_prompt
    if response_json:
        effective_system = (
            f"{effective_system}\n\n"
            "Return only one strict JSON object. Do not add markdown fences or prose."
        )

    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "system": effective_system,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            endpoint,
            headers={
                "Content-Type": "application/json",
                "x-api-key": str(settings.anthropic_api_key),
                "anthropic-version": settings.anthropic_api_version,
            },
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Anthropic request failed ({response.status_code}): {response.text}")

    body = response.json()
    content = body.get("content", [])
    if not isinstance(content, list):
        return ""
    texts = [str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"]
    return "".join(texts)
