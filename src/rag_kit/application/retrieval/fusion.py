"""Reciprocal rank fusion for heterogeneous retrieval results."""

from collections.abc import Sequence

from rag_kit.domain.models import ScoredChunk


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[ScoredChunk]], *, rrf_k: int = 60, top_k: int = 8
) -> list[ScoredChunk]:
    """Merge ranked results while retaining component scores as signals."""
    if rrf_k <= 0 or top_k < 0:
        raise ValueError("rrf_k must be positive and top_k nonnegative")  # noqa: TRY003
    scores: dict[str, float] = {}
    chunks: dict[str, ScoredChunk] = {}
    signals: dict[str, dict[str, float]] = {}
    for result_list in result_lists:
        for rank, result in enumerate(result_list, start=1):
            chunk_id = result.chunk.chunk_id
            chunks[chunk_id] = result
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (rrf_k + rank)
            signals.setdefault(chunk_id, {})[result.retriever] = result.score
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]
    return [
        ScoredChunk(
            chunk=chunks[chunk_id].chunk,
            score=scores[chunk_id],
            retriever="rrf",
            signals=signals[chunk_id],
        )
        for chunk_id in ordered
    ]
