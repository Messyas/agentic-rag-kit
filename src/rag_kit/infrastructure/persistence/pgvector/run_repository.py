"""PostgreSQL persistence for idempotent completed analysis results."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rag_kit.domain.analysis import AnalysisResult
from rag_kit.domain.errors import StoreError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PgRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def lock(self, idempotency_key: str):
        async with self._sessions() as session:
            await session.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": idempotency_key}
            )
            try:
                yield
            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": idempotency_key},
                )

    async def find(self, idempotency_key: str) -> AnalysisResult | None:
        try:
            async with self._sessions() as session:
                result = await session.execute(
                    text(
                        "SELECT result_json FROM analysis_runs WHERE idempotency_key=:key AND state='READY'"  # noqa: E501 - SQL statement remains readable as a multiline block
                    ),
                    {"key": idempotency_key},
                )
                row = result.mappings().first()
        except SQLAlchemyError as error:
            raise StoreError("failed to load cached analysis") from error  # noqa: TRY003
        if not row or row["result_json"] is None:
            return None
        try:
            return AnalysisResult.model_validate(row["result_json"])
        except ValidationError as error:
            raise StoreError("stored analysis has an invalid schema") from error  # noqa: TRY003

    async def save(self, idempotency_key: str, result: AnalysisResult) -> None:
        body = result.model_dump(mode="json")
        try:
            async with self._sessions.begin() as session:
                saved = await session.execute(
                    text(
                        "INSERT INTO analysis_runs(run_id,subject_id,subject_version,pipeline_version,"  # noqa: E501 - SQL statement remains readable as a multiline block
                        "idempotency_key,state,outcome,payload,result_json) VALUES "
                        "(CAST(:run_id AS uuid),:subject_id,:subject_version,:pipeline_version,:key,"  # noqa: E501 - SQL statement remains readable as a multiline block
                        "'READY',:outcome,CAST(:payload AS jsonb),CAST(:result AS jsonb)) "
                        "ON CONFLICT(idempotency_key) DO UPDATE SET state='READY',outcome=EXCLUDED.outcome,"  # noqa: E501 - SQL statement remains readable as a multiline block
                        "payload=EXCLUDED.payload,result_json=EXCLUDED.result_json,updated_at=now() "  # noqa: E501 - SQL statement remains readable as a multiline block
                        "RETURNING run_id"
                    ),
                    {
                        "run_id": result.run_id,
                        "subject_id": result.subject_id,
                        "subject_version": result.subject_version,
                        "pipeline_version": result.pipeline_version,
                        "key": idempotency_key,
                        "outcome": result.outcome.value,
                        "payload": json.dumps(body, ensure_ascii=False),
                        "result": json.dumps(body, ensure_ascii=False),
                    },
                )
                persisted_run_id = str(saved.scalar_one())
                await session.execute(
                    text("DELETE FROM analysis_run_sources WHERE run_id=CAST(:run_id AS uuid)"),
                    {"run_id": persisted_run_id},
                )
                for source in result.source_refs:
                    await session.execute(
                        text(
                            "INSERT INTO analysis_run_sources(run_id,source_type,source_id,source_version) "  # noqa: E501 - SQL statement remains readable as a multiline block
                            "VALUES (CAST(:run_id AS uuid),:source_type,:source_id,:source_version) "  # noqa: E501 - SQL statement remains readable as a multiline block
                            "ON CONFLICT DO NOTHING"
                        ),
                        {
                            "run_id": persisted_run_id,
                            "source_type": source.source_type,
                            "source_id": source.source_id,
                            "source_version": source.version,
                        },
                    )
        except SQLAlchemyError as error:
            raise StoreError("failed to persist analysis") from error  # noqa: TRY003
