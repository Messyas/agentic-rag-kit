"""Trace LLM usage and duration without prompt or response bodies."""

from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse
from rag_kit.domain.ports.tracer import Tracer
from rag_kit.infrastructure.llm.decorators.base import LLMDecorator


class TracingLLM(LLMDecorator):
    def __init__(self, inner: LLMClient, tracer: Tracer) -> None:
        super().__init__(inner)
        self._tracer = tracer

    async def complete(self, request: LLMRequest) -> LLMResponse:
        with self._tracer.span("llm", model=request.model) as span:
            response = await self.inner.complete(request)
            span.set("completion_tokens", response.usage.completion_tokens)
            return response
