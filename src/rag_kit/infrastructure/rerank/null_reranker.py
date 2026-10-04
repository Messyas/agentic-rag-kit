"""No-op reranker preserving the selected retrieval order."""

from collections.abc import Sequence

from rag_kit.domain.models import ScoredChunk


class NullReranker:
    async def rerank(
        self,
        query_text: str,  # noqa: ARG002 - Reranker contract
        candidates: Sequence[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        return list(candidates[:top_k])
