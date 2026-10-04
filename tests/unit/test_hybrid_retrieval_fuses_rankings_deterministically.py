"""RRF promotes repeated evidence and preserves the source retrieval signals."""

from rag_kit.application.retrieval.fusion import reciprocal_rank_fusion
from rag_kit.domain.models import Chunk, ScoredChunk, SourceRef, make_chunk_id


def _candidate(source_id: str, text: str, score: float, retriever: str) -> ScoredChunk:
    reference = SourceRef(source_type="review", source_id=source_id)
    chunk = Chunk(
        chunk_id=make_chunk_id(reference, 0, text),
        ref=reference,
        index=0,
        content=text,
    )
    return ScoredChunk(chunk=chunk, score=score, retriever=retriever)


def test_hybrid_retrieval_fuses_rankings_deterministically() -> None:
    first = _candidate("R1", "painel danificado transporte", 0.8, "dense")
    second = _candidate("R2", "falha de embalagem", 0.7, "dense")
    lexical_first = _candidate("R1", "painel danificado transporte", 0.9, "lexical")

    result = reciprocal_rank_fusion(((first, second), (lexical_first,)), top_k=2)

    assert [item.chunk.ref.source_id for item in result] == ["R1", "R2"]
    assert set(result[0].signals) == {"dense", "lexical"}
