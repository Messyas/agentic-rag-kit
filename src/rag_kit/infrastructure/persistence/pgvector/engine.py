"""Async PostgreSQL engine and pooled session factory."""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_kit.domain.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]


class _DatabaseSettings(Protocol):
    url: str
    pool_size: int
    hnsw_ef_search: int


def build_engine(settings: _DatabaseSettings) -> DatabaseRuntime:
    engine = create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_hnsw_ef_search(connection: Any, _: Any) -> None:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT set_config('hnsw.ef_search', %s, false)",
            (str(settings.hnsw_ef_search),),
        )
        cursor.close()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return DatabaseRuntime(engine=engine, sessions=sessions)


async def verify_schema(engine: AsyncEngine, dimension: int) -> None:
    async with engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        vector_type = await connection.scalar(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'chunk_embeddings' AND a.attname = 'embedding' "
                "AND NOT a.attisdropped"
            )
        )
    if not extension:
        raise ConfigurationError("pgvector extension is not installed")  # noqa: TRY003
    expected_type = f"vector({dimension})"
    if vector_type != expected_type:
        raise ConfigurationError(  # noqa: TRY003
            f"embedding column must be {expected_type}; found {vector_type!r}"
        )
