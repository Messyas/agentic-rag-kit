"""Candidate reranking protocol."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from rag_kit.domain.models import ScoredChunk


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self, query_text: str, candidates: Sequence[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]: ...
