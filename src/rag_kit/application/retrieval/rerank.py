"""Retriever decorator that reranks a widened candidate set."""

from rag_kit.domain.models import RetrievalQuery, ScoredChunk
from rag_kit.domain.ports.reranker import Reranker
from rag_kit.domain.ports.retriever import Retriever


class RerankingRetriever(Retriever):
    def __init__(self, base: Retriever, reranker: Reranker, candidate_multiplier: int = 3) -> None:
        if candidate_multiplier < 1:
            raise ValueError("candidate multiplier must be at least one")  # noqa: TRY003
        self._base = base
        self._reranker = reranker
        self._candidate_multiplier = candidate_multiplier

    @property
    def name(self) -> str:
        return f"{self._base.name}+rerank"

    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]:
        widened = query.model_copy(update={"k": query.k * self._candidate_multiplier})
        candidates = await self._base.retrieve(widened)
        return await self._reranker.rerank(query.text, candidates, query.k)
