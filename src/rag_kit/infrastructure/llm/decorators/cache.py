"""Bounded optional request cache scoped to one container."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import TYPE_CHECKING

from rag_kit.infrastructure.llm.decorators.base import LLMDecorator

if TYPE_CHECKING:
    from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse


class CachingLLM(LLMDecorator):
    def __init__(self, inner: LLMClient, max_entries: int = 128) -> None:
        super().__init__(inner)
        self._max_entries = max_entries
        self._cache: OrderedDict[str, LLMResponse] = OrderedDict()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        key = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].model_copy(
                deep=True,
                update={
                    "usage": self._cache[key].usage.model_copy(
                        update={"prompt_tokens": 0, "completion_tokens": 0, "total_duration_s": 0.0}
                    )
                },
            )
        response = await self.inner.complete(request)
        self._cache[key] = response.model_copy(deep=True)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
        return response
