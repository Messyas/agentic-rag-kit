"""Per-application dependency scope; objects are never shared across containers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rag_kit.application.agents.react_agent import InvestigationAgent
from rag_kit.application.agents.tool_calling import NativeToolCalling, StructuredToolCalling
from rag_kit.application.agents.tool_registry import ToolRegistry
from rag_kit.application.facade import AnalysisFacade, FacadeDependencies
from rag_kit.application.generation.generator import (
    RunnerOptions,
    StructuredGenerator,
    StructuredOutputRunner,
)
from rag_kit.application.generation.output_guard import (
    AbstentionGuard,
    GuardChain,
    HypothesisLabelGuard,
    InjectionEchoGuard,
    NumberParityGuard,
    SourceExistsGuard,
)
from rag_kit.application.generation.prompt_builder import PromptBuilder
from rag_kit.application.generation.prompt_registry import PromptRegistry
from rag_kit.application.grading.composite import CompositeGrader
from rag_kit.application.grading.llm_grader import LLMGrader
from rag_kit.application.grading.score_grader import NullGrader, ScoreGrader
from rag_kit.application.pack import PackDeps
from rag_kit.application.retrieval.dense import DenseRetriever
from rag_kit.application.retrieval.hybrid import HybridRetriever
from rag_kit.application.retrieval.lexical import LexicalRetriever
from rag_kit.application.retrieval.rerank import RerankingRetriever
from rag_kit.application.workflow.corrections import CorrectionPlanner, Reformulate
from rag_kit.application.workflow.corrective_rag import CorrectiveRagPipeline, PipelineIdentity
from rag_kit.application.workflow.nodes import RunContext
from rag_kit.application.workflow.policies import WorkflowPolicy
from rag_kit.bootstrap.factories import build_llm_client
from rag_kit.bootstrap.plugins import load_pack
from rag_kit.bootstrap.registry import Registry
from rag_kit.domain.errors import ConfigurationError
from rag_kit.domain.ports.pipeline import AnalysisPipeline
from rag_kit.infrastructure.embeddings.cache import CachingEmbedder
from rag_kit.infrastructure.embeddings.ollama_embedder import EmbeddingOptions, OllamaEmbedder
from rag_kit.infrastructure.embeddings.st_embedder import SentenceTransformerEmbedder
from rag_kit.infrastructure.loaders.csv_loader import CsvLoader
from rag_kit.infrastructure.loaders.xlsx_loader import XlsxLoader
from rag_kit.infrastructure.observability.tracer import JsonlTracer
from rag_kit.infrastructure.persistence.pgvector.engine import (
    DatabaseRuntime,
    build_engine,
    verify_schema,
)
from rag_kit.infrastructure.persistence.pgvector.run_repository import PgRunRepository
from rag_kit.infrastructure.persistence.pgvector.schema import upgrade_schema
from rag_kit.infrastructure.persistence.pgvector.store import PgVectorStore
from rag_kit.infrastructure.rerank.cross_encoder import CrossEncoderReranker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from rag_kit.application.pack import PackSpec
    from rag_kit.bootstrap.settings import Settings
    from rag_kit.domain.models import RawTable
    from rag_kit.domain.ports.embedder import Embedder
    from rag_kit.domain.ports.llm import LLMClient
    from rag_kit.domain.ports.retriever import Retriever

T = TypeVar("T")


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._instances: dict[str, Any] = {}
        self._closers: list[Callable[[], Awaitable[None]]] = []

    def load_table(self, path: Path) -> RawTable:
        """Select a concrete tabular adapter at the composition root."""
        if loader := self.pack.loaders.get(path.suffix.lower()):
            return loader.load(path)
        loader = XlsxLoader() if path.suffix.lower() == ".xlsx" else CsvLoader()
        return loader.load(path)

    @property
    def pack(self) -> PackSpec:
        return self._once("pack", lambda: load_pack(self.settings.pack.name))

    @property
    def tracer(self) -> JsonlTracer:
        return self._once(
            "tracer",
            lambda: JsonlTracer(Path(self.settings.observability.trace_dir) / "spans.jsonl"),
        )

    @property
    def llm(self) -> LLMClient:
        return self._once(
            "llm",
            lambda: build_llm_client(self.settings, self.tracer),
            lambda client: client.aclose(),
        )

    @property
    def embedder(self) -> Embedder:
        if self.settings.embedding.provider == "sentence_transformers":
            return self._once(
                "embedder",
                lambda: self._cached_embedder(
                    SentenceTransformerEmbedder(
                        self.settings.embedding.model, self.settings.embedding.device
                    )
                ),
                lambda adapter: adapter.aclose(),
            )
        return self._once(
            "embedder",
            lambda: self._cached_embedder(
                OllamaEmbedder(
                    EmbeddingOptions(
                        host=self.settings.ollama.host,
                        model=self.settings.ollama.embed_model,
                        batch_size=self.settings.embedding.batch_size,
                        keep_alive=self.settings.ollama.keep_alive,
                    )
                )
            ),
            lambda embedder: embedder.aclose(),
        )

    def _cached_embedder(self, embedder: Embedder) -> Embedder:
        if not self.settings.embedding.cache_enabled:
            return embedder
        return CachingEmbedder(embedder, self.settings.embedding.cache_capacity)

    @property
    def retriever(self) -> Retriever:
        if self.settings.rerank.provider == "cross_encoder":
            return self._once("reranked_retriever", self._build_reranked_retriever)
        return self._base_retriever()

    def _build_reranked_retriever(self) -> Retriever:

        reranker = CrossEncoderReranker(self.settings.rerank.model, self.settings.rerank.device)
        return RerankingRetriever(self._base_retriever(), reranker)

    def _base_retriever(self) -> Retriever:
        lexical = LexicalRetriever(self.vector_store)
        if self.settings.retrieval.mode == "lexical":
            return self._once("retriever", lambda: lexical)
        dense = DenseRetriever(self.vector_store, self.embedder, self.embedder.model_id)
        if self.settings.retrieval.mode == "dense":
            return self._once("retriever", lambda: dense)
        return self._once(
            "retriever", lambda: HybridRetriever(dense, lexical, self.settings.retrieval.rrf_k)
        )

    def build_facade(
        self,
        pack: PackSpec | None = None,
        pipeline_name: str = "corrective_rag",
        extras: dict[str, Any] | None = None,
    ) -> AnalysisFacade:
        """Compose the default pipeline; hosts may instead inject all domain ports."""
        selected = pack or self.pack
        selected.validate()
        ports = extras or {}
        retriever = cast("Retriever", ports.get("retriever") or self.retriever)
        prompts = PromptRegistry(selected.prompts_dir)
        runner = StructuredOutputRunner(
            self.llm,
            RunnerOptions(
                self.settings.ollama.llm_model,
                context_tokens=self.settings.workflow.max_context_tokens,
            ),
        )
        generator = StructuredGenerator(
            PromptBuilder(
                prompts,
                self.settings.workflow.max_context_tokens,
                self.settings.workflow.prompt_output_reserve_tokens,
            ),
            runner,
            selected,
        )
        guards = GuardChain(
            (
                SourceExistsGuard(),
                NumberParityGuard(),
                AbstentionGuard(),
                HypothesisLabelGuard(),
                InjectionEchoGuard(),
                *selected.guards(),
            )
        )
        context = RunContext(
            selected,
            retriever,
            CompositeGrader(ScoreGrader(), LLMGrader(runner, prompts)),
            generator,
            guards,
            self.tracer,
        )
        pipeline = self._pipeline(context, runner, ports, pipeline_name)
        return self._facade(selected, pipeline, retriever, ports)

    def _pipeline(
        self, context: RunContext, runner: StructuredOutputRunner, ports: dict[str, Any], name: str
    ) -> AnalysisPipeline:
        registry = Registry[AnalysisPipeline]("analysis pipeline")
        registry.register("corrective_rag")(lambda: self._workflow(context, runner))
        registry.register("simple_rag")(lambda: self._simple(context))
        registry.register("react_agent_native")(
            lambda: self._agent(context, runner, ports, "native")
        )
        registry.register("react_agent_structured_json")(
            lambda: self._agent(context, runner, ports, "structured_json")
        )
        return registry.create(name)

    def _workflow(
        self, context: RunContext, runner: StructuredOutputRunner
    ) -> CorrectiveRagPipeline:
        return CorrectiveRagPipeline(
            context,
            CorrectionPlanner(
                (
                    Reformulate(
                        runner,
                        PromptRegistry(context.pack.prompts_dir).render("reformulate.v1.jinja", {}),
                    ),
                )
            ),
            WorkflowPolicy(max_corrections=self.settings.workflow.max_corrections),
            PipelineIdentity(version=self.settings.workflow.pipeline_version),
        )

    def _simple(self, context: RunContext) -> CorrectiveRagPipeline:
        return CorrectiveRagPipeline(
            replace(context, grader=NullGrader()),
            CorrectionPlanner(()),
            WorkflowPolicy(max_corrections=0),
            PipelineIdentity("simple_rag", self.settings.workflow.pipeline_version),
        )

    def _agent(
        self, context: RunContext, runner: StructuredOutputRunner, ports: dict[str, Any], mode: str
    ) -> InvestigationAgent:
        tools = ToolRegistry(context.pack.build_tools(PackDeps(context.retriever, ports)))
        prompt = PromptRegistry(context.pack.prompts_dir).render("agent_system.v1.jinja", {})
        strategy = (
            NativeToolCalling(self.llm, self.settings.ollama.llm_model, prompt)
            if mode == "native"
            else StructuredToolCalling(self.llm, self.settings.ollama.llm_model, prompt)
        )
        return InvestigationAgent(tools, strategy, self._workflow(context, runner))

    def _facade(
        self,
        pack: PackSpec,
        pipeline: AnalysisPipeline,
        retriever: Retriever,
        ports: dict[str, Any],
    ) -> AnalysisFacade:
        prompts = PromptRegistry(pack.prompts_dir)
        revision = hashlib.sha256(
            (
                self.settings.model_dump_json()
                + json.dumps(pack.output_model.model_json_schema(), sort_keys=True)
                + "".join(
                    prompts.digest(path.name) for path in sorted(pack.prompts_dir.glob("*.jinja"))
                )
            ).encode()
        ).hexdigest()
        return AnalysisFacade(
            FacadeDependencies(
                pack,
                pipeline,
                retriever,
                self.vector_store,
                self.embedder,
                runs=ports.get("runs") or PgRunRepository(self.database.sessions),
                events=ports.get("events"),
                revision=revision,
                chunker=ports.get("chunker"),
                tracer=self.tracer,
                enricher=ports.get("enricher"),
            )
        )

    @property
    def database(self) -> DatabaseRuntime:
        return self._once(
            "database",
            lambda: build_engine(self.settings.database),
            lambda runtime: runtime.engine.dispose(),
        )

    @property
    def vector_store(self) -> PgVectorStore:
        return self._once(
            "vector_store",
            lambda: PgVectorStore(
                self.database.sessions,
                self.settings.database.hnsw_ef_search,
            ),
        )

    async def upgrade_database(self) -> None:
        await upgrade_schema(self.database.engine)

    async def check_database(self) -> dict[str, bool]:
        try:
            async with self.database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            await verify_schema(self.database.engine, 1024)
        except (SQLAlchemyError, ConfigurationError):
            return {"database_connected": False, "pgvector_schema_ready": False}
        return {"database_connected": True, "pgvector_schema_ready": True}

    async def check_ollama(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.settings.ollama.host.rstrip('/')}/api/tags")
                response.raise_for_status()
                payload: Any = response.json()
                raw_models: list[Any] = payload.get("models", [])
                model_names = {
                    str(cast("dict[str, Any]", item).get("name", ""))
                    for item in raw_models
                    if isinstance(item, dict)
                }
        except (httpx.HTTPError, ValueError):
            return {"ollama_available": False}
        return {
            "ollama_available": True,
            "llm_model_present": self.settings.ollama.llm_model in model_names,
            "embedding_model_present": self.settings.ollama.embed_model in model_names,
        }

    def _once(
        self, key: str, build: Callable[[], T], closer: Callable[[T], Awaitable[None]] | None = None
    ) -> T:
        if key not in self._instances:
            instance = build()
            self._instances[key] = instance
            if closer:
                self._closers.append(lambda instance=instance: closer(instance))
        return cast("T", self._instances[key])

    async def aclose(self) -> None:
        errors: list[Exception] = []
        while self._closers:
            try:
                await self._closers.pop()()
            except Exception as error:
                errors.append(error)
        self._instances.clear()
        if errors:
            raise ExceptionGroup("Errors closing application resources", errors)  # noqa: TRY003

    async def __aenter__(self) -> Container:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
