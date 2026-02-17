from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol


class LlmProvider(Protocol):
    async def __call__(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        response_json: bool = False,
    ) -> str: ...


class SqlProvider(Protocol):
    async def __call__(self, sql: str) -> list[dict[str, Any]]: ...


class AnalystProvider(Protocol):
    async def __call__(
        self,
        *,
        conversation_id: str,
        message: str,
        history: list[str] | None = None,
        route: str | None = None,
        step_id: str | None = None,
    ) -> dict[str, Any]: ...


LlmFn = Callable[..., Awaitable[str]]
SqlFn = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
