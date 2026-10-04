"""Concurrent dense and lexical retrieval followed by RRF fusion."""

import asyncio

from rag_kit.application.retrieval.fusion import reciprocal_rank_fusion
from rag_kit.domain.models import RetrievalQuery, ScoredChunk
from rag_kit.domain.ports.retriever import Retriever


class HybridRetriever(Retriever):
    def __init__(self, dense: Retriever, lexical: Retriever, rrf_k: int = 60) -> None:
        self._dense = dense
        self._lexical = lexical
        self._rrf_k = rrf_k

    @property
    def name(self) -> str:
        return "hybrid_rrf"

    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]:
        dense_query = query.model_copy(update={"k": max(query.k * 3, query.k)})
        lexical_query = dense_query
        dense, lexical = await asyncio.gather(
            self._dense.retrieve(dense_query), self._lexical.retrieve(lexical_query)
        )
        return reciprocal_rank_fusion((dense, lexical), rrf_k=self._rrf_k, top_k=query.k)
