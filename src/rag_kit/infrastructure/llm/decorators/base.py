"""Forwarding language-model decorator."""

from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse


class LLMDecorator:
    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self.inner.complete(request)

    async def aclose(self) -> None:
        await self.inner.aclose()
