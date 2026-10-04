"""Deterministic document chunking strategies preserving source lineage."""

from __future__ import annotations

from dataclasses import dataclass

from rag_kit.domain.models import Chunk, Document, make_chunk_id


def _chunk(document: Document, index: int, content: str) -> Chunk:
    return Chunk(
        chunk_id=make_chunk_id(document.ref, index, content),
        ref=document.ref,
        index=index,
        content=content,
        metadata=document.metadata,
    )


class RecordChunker:
    def chunk(self, document: Document) -> list[Chunk]:
        return [_chunk(document, 0, document.text)] if document.text.strip() else []


@dataclass(frozen=True, slots=True)
class FixedWindowChunker:
    size_words: int = 350
    overlap_words: int = 40

    def __post_init__(self) -> None:
        if self.size_words < 1 or not 0 <= self.overlap_words < self.size_words:
            raise ValueError("word window must be positive with smaller nonnegative overlap")  # noqa: TRY003

    def chunk(self, document: Document) -> list[Chunk]:
        words = document.text.split()
        if len(words) <= self.size_words:
            return RecordChunker().chunk(document)
        chunks: list[Chunk] = []
        start = 0
        while start < len(words):
            end = min(start + self.size_words, len(words))
            chunks.append(_chunk(document, len(chunks), " ".join(words[start:end])))
            if end == len(words):
                break
            start = end - self.overlap_words
        return chunks
