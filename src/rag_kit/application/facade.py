"""Stable host-facing API for corpus indexing and automatic analysis."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rag_kit.application.ingestion.chunkers import FixedWindowChunker
from rag_kit.domain.events import AnalysisFailed, AnalysisFinished, AnalysisStarted
from rag_kit.domain.ports.tracer import NullTracer
from rag_kit.domain.ports.vector_store import SourceIndex

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping, Sequence

    from rag_kit.application.pack import PackSpec
    from rag_kit.application.retrieval.enrich import ContextEnricher
    from rag_kit.domain.analysis import AnalysisResult, Subject
    from rag_kit.domain.models import Document
    from rag_kit.domain.ports.chunker import Chunker
    from rag_kit.domain.ports.embedder import Embedder
    from rag_kit.domain.ports.events import EventBus
    from rag_kit.domain.ports.pipeline import AnalysisPipeline
    from rag_kit.domain.ports.retriever import Retriever
    from rag_kit.domain.ports.runs import RunRepository
    from rag_kit.domain.ports.tracer import Tracer
    from rag_kit.domain.ports.vector_store import VectorWriter


@dataclass(frozen=True, slots=True)
class FacadeDependencies:
    pack: PackSpec
    pipeline: AnalysisPipeline
    retriever: Retriever
    writer: VectorWriter
    embedder: Embedder
    runs: RunRepository | None = None
    events: EventBus | None = None
    revision: str = "1"
    chunker: Chunker | None = None
    tracer: Tracer | None = None
    enricher: ContextEnricher | None = None


class AnalysisFacade:
    def __init__(self, dependencies: FacadeDependencies) -> None:
        self._deps = dependencies
        self._tracer = dependencies.tracer or NullTracer()
        self._chunker = dependencies.chunker or FixedWindowChunker()
        self._enricher = dependencies.enricher

    @property
    def name(self) -> str:
        return self._deps.pipeline.name

    @property
    def version(self) -> str:
        return self._deps.pipeline.version

    async def analyze(self, subject: Subject) -> AnalysisResult:
        pipeline = self._deps.pipeline
        version = (
            f"{self._deps.pack.name}:{subject.kind}:{pipeline.name}:"
            f"{pipeline.version}:{self._deps.revision}"
        )
        key = subject.idempotency_key(version)
        async with _analysis_lock(self._deps.runs, key):
            if self._deps.runs:
                cached = await self._deps.runs.find(key)
                if cached is not None:
                    return cached
            run_id = str(uuid.uuid4())
            await self._publish(AnalysisStarted(run_id, subject.subject_id))
            try:
                with self._tracer.span("analysis", run_id=run_id, pipeline=pipeline.name):
                    result = await pipeline.analyze(subject)
                result = result.model_copy(
                    update={
                        "run_id": run_id,
                        "pipeline_version": version,
                        "subject_version": subject.version,
                    }
                )
                if self._deps.runs:
                    await self._deps.runs.save(key, result)
            except Exception as error:
                await self._publish(
                    AnalysisFailed(run_id, subject.subject_id, type(error).__name__)
                )
                raise
            await self._publish(AnalysisFinished(run_id, subject.subject_id, result.outcome.value))
            return result

    async def _publish(self, event: object) -> None:
        if self._deps.events:
            await self._deps.events.publish(event)

    async def analyze_record(self, record: Mapping[str, Any]) -> AnalysisResult:
        return await self.analyze(self._deps.pack.subject_from_record(record))

    async def index_documents(self, documents: Sequence[Document]) -> int:
        count = 0
        for document in documents:
            chunks = self._chunker.chunk(document)
            if self._enricher:
                chunks = [await self._enricher.enrich(chunk) for chunk in chunks]
            content_hash = hashlib.sha256(
                json.dumps(
                    [
                        {"content": chunk.embedding_text, "metadata": chunk.metadata}
                        for chunk in chunks
                    ],
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                ).encode()
            ).hexdigest()
            if await self._deps.writer.source_is_current(
                document.ref, content_hash, self._deps.embedder.model_id
            ):
                count += len(chunks)
                continue
            embeddings = await self._deps.embedder.embed_documents(
                [chunk.embedding_text for chunk in chunks]
            )
            count += await self._deps.writer.replace_source(
                SourceIndex(
                    document.ref, chunks, embeddings, self._deps.embedder.model_id, content_hash
                )
            )
        return count

    async def index_records(self, records: Sequence[Mapping[str, Any]]) -> int:
        return await self.index_documents(
            [self._deps.pack.record_to_document(record) for record in records]
        )


@asynccontextmanager
async def _analysis_lock(repository: RunRepository | None, key: str) -> AsyncGenerator[None, None]:
    if repository is None:
        yield
        return
    async with repository.lock(key):
        yield
