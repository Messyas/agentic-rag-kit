"""PostgreSQL chunk repository implementing vector and lexical ports."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rag_kit.domain.errors import StoreError
from rag_kit.domain.models import Chunk, MetadataFilter, ScoredChunk, SourceRef
from rag_kit.infrastructure.persistence.pgvector.filters import compile_filters
from rag_kit.infrastructure.persistence.pgvector.lexical import build_or_tsquery

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from rag_kit.domain.ports.vector_store import SourceIndex


class PgVectorStore:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], hnsw_ef_search: int = 64
    ) -> None:
        self._sessions = sessions
        self._hnsw_ef_search = hnsw_ef_search

    async def source_is_current(self, ref: SourceRef, content_hash: str, embedder_id: str) -> bool:
        try:
            async with self._sessions() as session:
                result = await session.execute(
                    text(
                        "SELECT content_hash, embedder_id, source_version FROM indexed_sources "
                        "WHERE source_type=:source_type AND source_id=:source_id"
                    ),
                    {"source_type": ref.source_type, "source_id": ref.source_id},
                )
                current = result.mappings().first()
        except SQLAlchemyError as exc:
            raise StoreError("failed to inspect indexed source") from exc  # noqa: TRY003
        return bool(
            current
            and current["content_hash"] == content_hash
            and current["embedder_id"] == embedder_id
            and current["source_version"] == ref.version
        )

    async def replace_source(self, snapshot: SourceIndex) -> int:
        """Replace all revisions atomically, including shortened or empty sources."""
        parameters = {
            "source_type": snapshot.ref.source_type,
            "source_id": snapshot.ref.source_id,
            "lock_key": snapshot.ref.source_type + ":" + snapshot.ref.source_id,
        }
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    parameters,
                )
                await session.execute(
                    text(
                        "UPDATE analysis_runs SET state='STALE', updated_at=now() "
                        "WHERE run_id IN (SELECT run_id FROM analysis_run_sources "
                        "WHERE source_type=:source_type AND source_id=:source_id "
                        "AND analysis_runs.state='READY')"
                    ),
                    {**parameters, "source_version": snapshot.ref.version},
                )
                await session.execute(
                    text(
                        "DELETE FROM chunks WHERE source_type=:source_type AND source_id=:source_id"
                    ),
                    parameters,
                )
                for chunk, embedding in zip(snapshot.chunks, snapshot.embeddings, strict=True):
                    await self._upsert_one(session, chunk, embedding, snapshot.embedder_id)
                await session.execute(
                    text(
                        "INSERT INTO indexed_sources(source_type,source_id,source_version,content_hash,embedder_id) "  # noqa: E501 - SQL statement remains readable as a multiline block
                        "VALUES (:source_type,:source_id,:source_version,:content_hash,:embedder_id) "  # noqa: E501 - SQL statement remains readable as a multiline block
                        "ON CONFLICT(source_type,source_id) DO UPDATE SET source_version=EXCLUDED.source_version, "  # noqa: E501 - SQL statement remains readable as a multiline block
                        "content_hash=EXCLUDED.content_hash, embedder_id=EXCLUDED.embedder_id, updated_at=now()"  # noqa: E501 - SQL statement remains readable as a multiline block
                    ),
                    {
                        **parameters,
                        "source_version": snapshot.ref.version,
                        "content_hash": snapshot.content_hash,
                        "embedder_id": snapshot.embedder_id,
                    },
                )
        except SQLAlchemyError as exc:
            raise StoreError("failed to replace source snapshot") from exc  # noqa: TRY003
        return len(snapshot.chunks)

    async def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        *,
        embedder_id: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise StoreError("chunk and embedding counts differ")  # noqa: TRY003
        try:
            async with self._sessions.begin() as session:
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    await self._upsert_one(session, chunk, embedding, embedder_id)
        except SQLAlchemyError as exc:
            raise StoreError("failed to upsert chunks") from exc  # noqa: TRY003
        return len(chunks)

    async def _upsert_one(
        self,
        session: AsyncSession,
        chunk: Chunk,
        embedding: Sequence[float],
        embedder_id: str,
    ) -> None:
        content_hash = hashlib.sha256(chunk.embedding_text.encode()).hexdigest()
        parameters = self._chunk_parameters(chunk, content_hash)
        await session.execute(
            text(
                "DELETE FROM chunks WHERE source_type=:source_type AND source_id=:source_id "
                "AND source_version=:source_version AND chunk_index=:chunk_index "
                "AND chunk_id<>:chunk_id"
            ),
            parameters,
        )
        await session.execute(
            text(
                "INSERT INTO chunks (chunk_id, source_type, source_id, source_version, "
                "chunk_index, content, context_prefix, metadata, content_hash) "
                "VALUES (:chunk_id, :source_type, :source_id, :source_version, :chunk_index, "
                ":content, :context_prefix, CAST(:metadata AS jsonb), :content_hash) "
                "ON CONFLICT (chunk_id) DO UPDATE SET content=EXCLUDED.content, "
                "context_prefix=EXCLUDED.context_prefix, metadata=EXCLUDED.metadata, "
                "content_hash=EXCLUDED.content_hash "
                "WHERE chunks.content_hash<>EXCLUDED.content_hash "
                "OR chunks.metadata IS DISTINCT FROM EXCLUDED.metadata"
            ),
            parameters,
        )
        await session.execute(
            text(
                "INSERT INTO chunk_embeddings (chunk_id, embedder_id, embedding) "
                "VALUES (:chunk_id, :embedder_id, CAST(:embedding AS vector)) "
                "ON CONFLICT (chunk_id, embedder_id) DO UPDATE SET embedding=EXCLUDED.embedding"
            ),
            {
                "chunk_id": chunk.chunk_id,
                "embedder_id": embedder_id,
                "embedding": _vector_literal(embedding),
            },
        )

    def _chunk_parameters(self, chunk: Chunk, content_hash: str) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "source_type": chunk.ref.source_type,
            "source_id": chunk.ref.source_id,
            "source_version": chunk.ref.version,
            "chunk_index": chunk.index,
            "content": chunk.content,
            "context_prefix": chunk.context_prefix,
            "metadata": json.dumps(chunk.metadata, ensure_ascii=False, default=str),
            "content_hash": content_hash,
        }

    async def delete_source(self, ref: SourceRef) -> int:
        try:
            async with self._sessions.begin() as session:
                result = await session.execute(
                    text(
                        "DELETE FROM chunks WHERE source_type=:source_type "
                        "AND source_id=:source_id "
                        "AND source_version=:source_version"
                    ),
                    {
                        "source_type": ref.source_type,
                        "source_id": ref.source_id,
                        "source_version": ref.version,
                    },
                )
                await session.execute(
                    text(
                        "DELETE FROM indexed_sources WHERE source_type=:source_type AND source_id=:source_id"  # noqa: E501 - SQL statement remains readable as a multiline block
                    ),
                    {"source_type": ref.source_type, "source_id": ref.source_id},
                )
                await session.execute(
                    text(
                        "UPDATE analysis_runs SET state='STALE', updated_at=now() "
                        "WHERE run_id IN (SELECT run_id FROM analysis_run_sources "
                        "WHERE source_type=:source_type AND source_id=:source_id AND source_version=:source_version)"  # noqa: E501 - SQL statement remains readable as a multiline block
                    ),
                    {
                        "source_type": ref.source_type,
                        "source_id": ref.source_id,
                        "source_version": ref.version,
                    },
                )
            deleted_count = cast("int", getattr(result, "rowcount", 0))
        except SQLAlchemyError as exc:
            raise StoreError("failed to delete source chunks") from exc  # noqa: TRY003
        else:
            return deleted_count

    async def search_dense(
        self,
        query_embedding: Sequence[float],
        *,
        k: int,
        embedder_id: str,
        filters: Sequence[MetadataFilter] = (),
    ) -> list[ScoredChunk]:
        if k <= 0:
            return []
        compiled = compile_filters(filters)
        statement = text(
            "SELECT c.chunk_id, c.source_type, c.source_id, c.source_version, c.chunk_index, "
            "c.content, c.context_prefix, c.metadata, "
            "1 - (e.embedding <=> CAST(:query_vector AS vector)) AS score "
            "FROM chunk_embeddings e JOIN chunks c USING (chunk_id) "
            "WHERE e.embedder_id=:embedder_id" + compiled.sql_fragment + " "
            "ORDER BY e.embedding <=> CAST(:query_vector AS vector) LIMIT :k"
        )
        return await self._search(
            statement,
            {
                **compiled.bind_parameters,
                "query_vector": _vector_literal(query_embedding),
                "embedder_id": embedder_id,
                "k": k,
            },
            "dense",
        )

    async def search_lexical(
        self, query: str, *, k: int, filters: Sequence[MetadataFilter] = ()
    ) -> list[ScoredChunk]:
        tsquery = build_or_tsquery(query)
        if not tsquery or k <= 0:
            return []
        compiled = compile_filters(filters)
        statement = text(
            "SELECT c.chunk_id, c.source_type, c.source_id, c.source_version, c.chunk_index, "
            "c.content, c.context_prefix, c.metadata, ts_rank_cd(c.tsv, q, 32) AS score "
            "FROM chunks c, to_tsquery('portuguese', :query) AS q "
            "WHERE c.tsv @@ q" + compiled.sql_fragment + " ORDER BY score DESC LIMIT :k"
        )
        return await self._search(
            statement, {**compiled.bind_parameters, "query": tsquery, "k": k}, "lexical"
        )

    async def _search(
        self, statement: Any, parameters: dict[str, Any], retriever: str
    ) -> list[ScoredChunk]:
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT set_config('hnsw.ef_search', :setting, true)"),
                    {"setting": str(self._hnsw_ef_search)},
                )
                result = await session.execute(statement, parameters)
                rows = result.mappings().all()
        except SQLAlchemyError as exc:
            raise StoreError(f"{retriever} search failed") from exc  # noqa: TRY003
        return [_scored_chunk(dict(row), retriever) for row in rows]


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _scored_chunk(row: dict[str, Any], retriever: str) -> ScoredChunk:
    reference = SourceRef(
        source_type=row["source_type"],
        source_id=row["source_id"],
        version=row["source_version"],
    )
    chunk = Chunk(
        chunk_id=row["chunk_id"],
        ref=reference,
        index=row["chunk_index"],
        content=row["content"],
        context_prefix=row["context_prefix"],
        metadata=row["metadata"],
    )
    return ScoredChunk(chunk=chunk, score=float(row["score"]), retriever=retriever)
