"""Circuit breaker preventing repeated requests to an unavailable provider."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rag_kit.domain.errors import CircuitOpenError, LLMTransientError
from rag_kit.infrastructure.llm.decorators.base import LLMDecorator

if TYPE_CHECKING:
    from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    failures: int = 5
    reset_s: float = 30.0


class CircuitBreakerLLM(LLMDecorator):
    def __init__(self, inner: LLMClient, policy: CircuitBreakerPolicy | None = None) -> None:
        super().__init__(inner)
        self._policy = policy or CircuitBreakerPolicy()
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        async with self._lock:
            if (
                self._opened_at is not None
                and time.monotonic() - self._opened_at < self._policy.reset_s
            ):
                raise CircuitOpenError("provider circuit is open")  # noqa: TRY003 - contextual domain error
            try:
                response = await self.inner.complete(request)
            except LLMTransientError:
                self._failures += 1
                if self._failures >= self._policy.failures:
                    self._opened_at = time.monotonic()
                raise
            self._failures = 0
            self._opened_at = None
            return response
