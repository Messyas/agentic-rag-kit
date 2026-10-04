"""Idempotent local schema upgrade and downgrade operations."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

UPGRADE_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS chunks (
        chunk_id text PRIMARY KEY,
        source_type text NOT NULL,
        source_id text NOT NULL,
        source_version text NOT NULL,
        chunk_index integer NOT NULL,
        content text NOT NULL,
        context_prefix text NOT NULL DEFAULT '',
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        content_hash text NOT NULL,
        tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('portuguese', coalesce(context_prefix, '') || ' ' || content)
        ) STORED,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (source_type, source_id, source_version, chunk_index)
    )""",
    """CREATE TABLE IF NOT EXISTS chunk_embeddings (
        chunk_id text NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
        embedder_id text NOT NULL,
        embedding vector(1024) NOT NULL,
        PRIMARY KEY (chunk_id, embedder_id)
    )""",
    """CREATE TABLE IF NOT EXISTS analysis_runs (
        run_id uuid PRIMARY KEY,
        subject_id text NOT NULL,
        subject_version text NOT NULL,
        pipeline_version text NOT NULL,
        idempotency_key text NOT NULL UNIQUE,
        state text NOT NULL,
        outcome text,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        trace_path text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS chunk_embeddings_hnsw ON chunk_embeddings "
    "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
    "CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS chunks_meta_gin ON chunks USING gin (metadata jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS chunks_source_ix ON chunks (source_type, source_id)",
    "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS result_json jsonb",
    """CREATE TABLE IF NOT EXISTS analysis_run_sources (
        run_id uuid NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
        source_type text NOT NULL,
        source_id text NOT NULL,
        source_version text NOT NULL,
        PRIMARY KEY(run_id, source_type, source_id, source_version)
    )""",
    """CREATE TABLE IF NOT EXISTS indexed_sources (
        source_type text NOT NULL,
        source_id text NOT NULL,
        source_version text NOT NULL,
        content_hash text NOT NULL,
        embedder_id text NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (source_type, source_id)
    )""",
)


async def upgrade_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        for statement in UPGRADE_STATEMENTS:
            await connection.execute(text(statement))


async def downgrade_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS analysis_runs"))
        await connection.execute(text("DROP TABLE IF EXISTS indexed_sources"))
        await connection.execute(text("DROP TABLE IF EXISTS chunk_embeddings"))
        await connection.execute(text("DROP TABLE IF EXISTS chunks"))
