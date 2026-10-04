"""Document chunking protocol."""

from typing import Protocol, runtime_checkable

from rag_kit.domain.models import Chunk, Document


@runtime_checkable
class Chunker(Protocol):
    def chunk(self, document: Document) -> list[Chunk]: ...
