"""Deterministic adapters shared by application and contract tests."""

from __future__ import annotations

import hashlib
import math
from collections import deque
from typing import TYPE_CHECKING, Any

from rag_kit.domain.models import Chunk, MetadataFilter, ScoredChunk, SourceRef
from rag_kit.domain.ports.llm import LLMRequest, LLMResponse, LLMUsage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rag_kit.domain.ports.vector_store import SourceIndex


class FakeLLM:
    def __init__(self, responses: Sequence[LLMResponse | Exception] = ()) -> None:
        self._responses = deque(responses)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        response = (
            self._responses.popleft()
            if self._responses
            else LLMResponse(content="{}", model=request.model, usage=LLMUsage())
        )
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        return None


class HashEmbedder:
    def __init__(self, dimension: int = 32, model_id: str = "hash-test-v1") -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")  # noqa: TRY003
        self.dimension = dimension
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in text.casefold().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[Chunk, tuple[float, ...], str]] = {}
        self._source_hashes: dict[tuple[str, str], tuple[str, str, str]] = {}

    async def replace_source(self, snapshot: SourceIndex) -> int:
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if (entry[0].ref.source_type, entry[0].ref.source_id)
            != (snapshot.ref.source_type, snapshot.ref.source_id)
        }
        self._source_hashes[(snapshot.ref.source_type, snapshot.ref.source_id)] = (
            snapshot.ref.version, snapshot.content_hash, snapshot.embedder_id
        )
        return await self.upsert(
            snapshot.chunks, snapshot.embeddings, embedder_id=snapshot.embedder_id
        )

    async def source_is_current(self, ref: SourceRef, content_hash: str, embedder_id: str) -> bool:
        return self._source_hashes.get((ref.source_type, ref.source_id)) == (
            ref.version, content_hash, embedder_id
        )

    async def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        *,
        embedder_id: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding counts differ")  # noqa: TRY003
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._entries[chunk.chunk_id] = (chunk, tuple(embedding), embedder_id)
        return len(chunks)

    async def delete_source(self, ref: SourceRef) -> int:
        identifiers = [key for key, (chunk, _, _) in self._entries.items() if chunk.ref == ref]
        for identifier in identifiers:
            del self._entries[identifier]
        self._source_hashes.pop((ref.source_type, ref.source_id), None)
        return len(identifiers)

    async def search_dense(
        self,
        query_embedding: Sequence[float],
        *,
        k: int,
        embedder_id: str,
        filters: Sequence[MetadataFilter] = (),
    ) -> list[ScoredChunk]:
        query_norm = math.sqrt(sum(value * value for value in query_embedding)) or 1.0
        scored: list[ScoredChunk] = []
        for chunk, vector, stored_embedder in self._entries.values():
            if stored_embedder != embedder_id or not _matches(chunk, filters):
                continue
            vector_norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            score = sum(left * right for left, right in zip(query_embedding, vector, strict=False))
            score /= query_norm * vector_norm
            scored.append(ScoredChunk(chunk=chunk, score=score, retriever="dense"))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:k]

    async def search_lexical(
        self, query: str, *, k: int, filters: Sequence[MetadataFilter] = ()
    ) -> list[ScoredChunk]:
        query_tokens = set(query.casefold().split())
        scored = []
        for chunk, _, _ in self._entries.values():
            if not _matches(chunk, filters):
                continue
            tokens = set(chunk.content.casefold().split())
            overlap = len(query_tokens & tokens) / len(query_tokens) if query_tokens else 0.0
            if overlap:
                scored.append(ScoredChunk(chunk=chunk, score=overlap, retriever="lexical"))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:k]


def _matches(chunk: Chunk, filters: Sequence[MetadataFilter]) -> bool:  # noqa: PLR0911
    for item in filters:
        actual: Any = (
            getattr(chunk.ref, item.field)
            if item.field in {"source_type", "source_id", "version"}
            else chunk.metadata.get(item.field)
        )
        if item.op == "eq" and actual != item.value:
            return False
        if item.op == "in" and actual not in item.value:
            return False
        if item.op == "gte" and (actual is None or actual < item.value):
            return False
        if item.op == "lte" and (actual is None or actual > item.value):
            return False
    return True
