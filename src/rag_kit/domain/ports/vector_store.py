"""Separated write, dense-search, and lexical-search ports."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rag_kit.domain.models import Chunk, MetadataFilter, ScoredChunk, SourceRef


@dataclass(frozen=True, slots=True)
class SourceIndex:
    """Complete current snapshot of one logical evidence source."""

    ref: SourceRef
    chunks: Sequence[Chunk]
    embeddings: Sequence[Sequence[float]]
    embedder_id: str
    content_hash: str = ""

    def __post_init__(self) -> None:
        if len(self.chunks) != len(self.embeddings):
            raise ValueError("chunk and embedding counts differ")  # noqa: TRY003
        if any(chunk.ref != self.ref for chunk in self.chunks):
            raise ValueError("snapshot chunks must belong to its source")  # noqa: TRY003


@runtime_checkable
class VectorWriter(Protocol):
    async def source_is_current(
        self, ref: SourceRef, content_hash: str, embedder_id: str
    ) -> bool: ...
    async def replace_source(self, snapshot: SourceIndex) -> int: ...
    async def upsert(
        self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]], *, embedder_id: str
    ) -> int: ...
    async def delete_source(self, ref: SourceRef) -> int: ...


@runtime_checkable
class VectorReader(Protocol):
    async def search_dense(
        self,
        query_embedding: Sequence[float],
        *,
        k: int,
        embedder_id: str,
        filters: Sequence[MetadataFilter] = (),
    ) -> list[ScoredChunk]: ...


@runtime_checkable
class LexicalReader(Protocol):
    async def search_lexical(
        self, query: str, *, k: int, filters: Sequence[MetadataFilter] = ()
    ) -> list[ScoredChunk]: ...
