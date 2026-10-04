"""Host-provided storage boundary for versioned analysis runs."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from rag_kit.domain.analysis import AnalysisResult


class RunRepository(Protocol):
    def lock(self, idempotency_key: str) -> AbstractAsyncContextManager[None]: ...
    async def find(self, idempotency_key: str) -> AnalysisResult | None: ...
    async def save(self, idempotency_key: str, result: AnalysisResult) -> None: ...
