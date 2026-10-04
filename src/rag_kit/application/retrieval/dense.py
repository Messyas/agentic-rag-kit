"""Dense retrieval strategy using an embedder and vector reader port."""

from rag_kit.domain.models import MetadataFilter, RetrievalQuery, ScoredChunk
from rag_kit.domain.ports.embedder import Embedder
from rag_kit.domain.ports.retriever import Retriever
from rag_kit.domain.ports.vector_store import VectorReader


class DenseRetriever(Retriever):
    def __init__(self, reader: VectorReader, embedder: Embedder, embedder_id: str) -> None:
        self._reader = reader
        self._embedder = embedder
        self._embedder_id = embedder_id

    @property
    def name(self) -> str:
        return "dense"

    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]:
        embedding = await self._embedder.embed_query(query.text)
        return await self._reader.search_dense(
            embedding,
            k=query.k,
            embedder_id=self._embedder_id,
            filters=query.filters
            + (
                (MetadataFilter(field="source_type", op="in", value=query.source_types),)
                if query.source_types
                else ()
            ),
        )
