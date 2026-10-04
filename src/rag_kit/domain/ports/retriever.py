"""Evidence retrieval protocol."""

from typing import Protocol, runtime_checkable

from rag_kit.domain.models import RetrievalQuery, ScoredChunk


@runtime_checkable
class Retriever(Protocol):
    @property
    def name(self) -> str: ...
    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]: ...
