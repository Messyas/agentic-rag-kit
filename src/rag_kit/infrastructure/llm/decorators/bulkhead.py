"""Per-container concurrency limit for local GPU inference."""

import asyncio

from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse
from rag_kit.infrastructure.llm.decorators.base import LLMDecorator


class BulkheadLLM(LLMDecorator):
    def __init__(self, inner: LLMClient, max_concurrent: int = 1) -> None:
        super().__init__(inner)
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")  # noqa: TRY003 - contextual domain error
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        async with self._semaphore:
            return await self.inner.complete(request)
