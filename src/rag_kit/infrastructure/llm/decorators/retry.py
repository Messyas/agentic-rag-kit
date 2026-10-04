"""Retry transient local inference failures only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rag_kit.domain.errors import LLMTransientError
from rag_kit.infrastructure.llm.decorators.base import LLMDecorator

if TYPE_CHECKING:
    from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.2


class RetryingLLM(LLMDecorator):
    def __init__(self, inner: LLMClient, policy: RetryPolicy | None = None) -> None:
        super().__init__(inner)
        if (policy or RetryPolicy()).max_attempts < 1:
            raise ValueError("retry attempts must be positive")  # noqa: TRY003 - contextual domain error
        self._policy = policy or RetryPolicy()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        for attempt in range(self._policy.max_attempts):
            try:
                return await self.inner.complete(request)
            except LLMTransientError:
                if attempt + 1 == self._policy.max_attempts:
                    raise
                await asyncio.sleep(self._policy.base_delay_s * 2**attempt)
        raise AssertionError("unreachable retry state")  # noqa: TRY003 - contextual domain error
