"""Lexical retrieval strategy delegating to the lexical reader port."""

from rag_kit.domain.models import MetadataFilter, RetrievalQuery, ScoredChunk
from rag_kit.domain.ports.retriever import Retriever
from rag_kit.domain.ports.vector_store import LexicalReader


class LexicalRetriever(Retriever):
    def __init__(self, reader: LexicalReader) -> None:
        self._reader = reader

    @property
    def name(self) -> str:
        return "lexical"

    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]:
        filters = query.filters + (
            (MetadataFilter(field="source_type", op="in", value=query.source_types),)
            if query.source_types
            else ()
        )
        return await self._reader.search_lexical(query.text, k=query.k, filters=filters)
