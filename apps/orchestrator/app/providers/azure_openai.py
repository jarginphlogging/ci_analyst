from __future__ import annotations

import httpx
from typing import Any, Optional

from app.config import settings


def _chat_endpoint() -> str:
    if not settings.has_azure_credentials():
        raise RuntimeError(
            "Azure OpenAI credentials are not configured. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT."
        )

    return (
        f"{settings.azure_openai_endpoint}/openai/deployments/{settings.azure_openai_deployment}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )


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
            headers={
                "Content-Type": "application/json",
                "api-key": str(settings.azure_openai_api_key),
            },
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Azure OpenAI request failed ({response.status_code}): {response.text}")

    payload = response.json()
    choices = payload.get("choices", [])
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
