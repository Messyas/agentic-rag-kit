"""Local evaluation composition with fresh containers and scoped corpus sources."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from evaluation.baselines.rule_baseline import RuleBaseline
from evaluation.dataset import load_dataset
from evaluation.runner import EvaluationRun, run_evaluation
from rag_kit.application.generation.prompt_registry import PromptRegistry
from rag_kit.application.retrieval.enrich import ContextEnricher
from rag_kit.application.retrieval.lexical import LexicalRetriever
from rag_kit.bootstrap.container import Container
from rag_kit.domain.models import (
    Document,
    MetadataFilter,
    RetrievalQuery,
    ScoredChunk,
    SourceRef,
    make_chunk_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from evaluation.dataset import EvaluationDataset
    from rag_kit.bootstrap.settings import Settings
    from rag_kit.domain.analysis import AnalysisResult, Subject
    from rag_kit.domain.ports.pipeline import AnalysisPipeline
    from rag_kit.domain.ports.retriever import Retriever


@dataclass(frozen=True, slots=True)
class LocalEvaluationOptions:
    dataset_directory: Path
    output_directory: Path
    split: str = "dev"
    arms: tuple[str, ...] = (
        "rule_baseline",
        "simple_rag",
        "corrective_rag",
        "react_agent_native",
        "react_agent_structured_json",
    )
    repeat_count: int = 1
    warmup_cases: int = 2

    def __post_init__(self) -> None:
        allowed = {
            "rule_baseline",
            "simple_rag",
            "corrective_rag",
            "react_agent_native",
            "react_agent_structured_json",
            "A0",
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
        }
        if not self.arms or len(set(self.arms)) != len(self.arms) or set(self.arms) - allowed:
            raise ValueError("evaluation arms must be distinct supported pipelines")  # noqa: TRY003
        if self.split not in {"dev", "test"} or self.repeat_count < 1 or self.warmup_cases < 0:
            raise ValueError("invalid evaluation split or repetition counts")  # noqa: TRY003


class CaseScopedRetriever:
    def __init__(self, inner: Retriever, scope: str) -> None:
        self._inner = inner
        self._scope = scope
        self.allowed: tuple[str, ...] = ()
        self.retrieved_sources: list[str] = []

    @property
    def name(self) -> str:
        return self._inner.name

    async def retrieve(self, query: RetrievalQuery) -> list[ScoredChunk]:
        if not self.allowed:
            return []
        filters = (
            *query.filters,
            MetadataFilter(field="eval_namespace", value=self._scope),
            MetadataFilter(field="eval_original_source_id", op="in", value=list(self.allowed)),
        )
        source_types = tuple(f"{self._scope}:{source_type}" for source_type in query.source_types)
        hits = await self._inner.retrieve(
            query.model_copy(update={"filters": filters, "source_types": source_types})
        )
        restored = [_restore_source(hit) for hit in hits]
        self.retrieved_sources.extend(hit.chunk.ref.source_id for hit in restored)
        return restored


def _restore_source(hit: ScoredChunk) -> ScoredChunk:
    original = hit.chunk.metadata["eval_original_source_id"]
    ref = hit.chunk.ref.model_copy(
        update={
            "source_id": original,
            "source_type": hit.chunk.metadata["eval_original_source_type"],
        }
    )
    chunk = hit.chunk.model_copy(
        update={"ref": ref, "chunk_id": make_chunk_id(ref, hit.chunk.index, hit.chunk.content)}
    )
    return hit.model_copy(update={"chunk": chunk})


class CasePipeline:
    def __init__(
        self, inner: AnalysisPipeline, retriever: CaseScopedRetriever, dataset: EvaluationDataset
    ) -> None:
        self._inner = inner
        self._retriever = retriever
        self._sources = {case.case_id: tuple(case.corpus_document_ids) for case in dataset.cases}

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def version(self) -> str:
        return self._inner.version

    async def analyze(self, subject: Subject) -> AnalysisResult:
        self._retriever.allowed = self._sources[subject.subject_id]
        self._retriever.retrieved_sources.clear()
        result = await self._inner.analyze(subject)
        return result.model_copy(
            update={
                "usage": {
                    **result.usage,
                    "retrieved_source_ids": list(dict.fromkeys(self._retriever.retrieved_sources)),
                }
            }
        )


class _EvaluationRunRepository:
    @asynccontextmanager
    async def lock(self, idempotency_key: str):  # noqa: ARG002 - repository port
        yield

    async def find(self, idempotency_key: str):  # noqa: ARG002 - repository port
        return None

    async def save(self, idempotency_key: str, result: AnalysisResult) -> None:  # noqa: ARG002
        return None


async def evaluate_local(
    settings: Settings, options: LocalEvaluationOptions
) -> dict[str, dict[str, Any]]:
    settings = settings.model_copy(
        update={
            "llm": settings.llm.model_copy(update={"cache_enabled": False, "max_concurrent": 1})
        }
    )
    dataset = load_dataset(options.dataset_directory)
    options.output_directory.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    for arm in options.arms:
        summaries.update(await _evaluate_arm(settings, options, dataset, arm))
    manifest: dict[str, Any] = {
        "split": options.split,
        "arms": list(options.arms),
        "seed": 42,
        "repeat_count": options.repeat_count,
        "warmup_cases": options.warmup_cases,
        "dataset_sha256": hashlib.sha256(dataset.model_dump_json().encode()).hexdigest(),
        "llm_model": settings.ollama.llm_model,
        "embedding_model": settings.ollama.embed_model,
        "retrieval_mode": settings.retrieval.mode,
        "reranker": settings.rerank.provider,
    }
    prompts = PromptRegistry(Container(settings).pack.prompts_dir)
    manifest["prompt_sha256"] = {
        name: prompts.digest(name)
        for name in ("generator.v1.jinja", "grader.v1.jinja", "agent_system.v1.jinja")
    }
    (options.output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _write_report(options, summaries)
    return summaries


async def _evaluate_arm(
    settings: Settings, options: LocalEvaluationOptions, dataset: EvaluationDataset, arm: str
) -> dict[str, dict[str, Any]]:
    settings, pipeline_name, enrich = _arm_configuration(settings, arm)
    scope = "evaluation:" + str(uuid.uuid4())
    documents = [
        Document(
            ref=SourceRef(
                source_type=f"{scope}:{document.source_type}",
                source_id=f"{scope}:{document.document_id}",
            ),
            text=document.text,
            metadata={
                **document.metadata,
                "eval_namespace": scope,
                "eval_original_source_id": document.document_id,
                "eval_original_source_type": document.source_type,
            },
        )
        for document in dataset.corpus
    ]
    async with Container(settings) as container:
        retriever = CaseScopedRetriever(
            LexicalRetriever(container.vector_store)
            if arm == "rule_baseline"
            else container.retriever,
            scope,
        )
        facade = container.build_facade(
            extras={
                "retriever": retriever,
                "runs": _EvaluationRunRepository(),
                **({"enricher": _context_enricher(container)} if enrich else {}),
            },
            pipeline_name="corrective_rag" if arm == "rule_baseline" else pipeline_name,
        )
        pipeline: AnalysisPipeline = RuleBaseline(retriever) if arm == "rule_baseline" else facade
        try:
            await facade.index_documents(documents)
            return await run_evaluation(
                EvaluationRun(
                    {arm: CasePipeline(pipeline, retriever, dataset)},
                    dataset,
                    options.split,
                    options.output_directory,
                    options.warmup_cases,
                    options.repeat_count,
                )
            )
        finally:
            for document in documents:
                await container.vector_store.delete_source(document.ref)


def _arm_configuration(settings: Settings, arm: str) -> tuple[Settings, str, bool]:
    configs = {
        "A0": ("dense", "none", "simple_rag", False),
        "A1": ("hybrid", "none", "simple_rag", False),
        "A2": ("hybrid", "cross_encoder", "simple_rag", False),
        "A3": ("hybrid", "cross_encoder", "simple_rag", True),
        "A4": ("hybrid", "cross_encoder", "corrective_rag", True),
        "A5": ("hybrid", "cross_encoder", "react_agent_native", True),
    }
    if arm not in configs:
        return settings, arm, False
    retrieval, rerank, pipeline, enrich = configs[arm]
    configured = settings.model_copy(
        update={
            "retrieval": settings.retrieval.model_copy(update={"mode": retrieval}),
            "rerank": settings.rerank.model_copy(update={"provider": rerank}),
        }
    )
    return configured, pipeline, enrich


def _context_enricher(container: Container) -> ContextEnricher:
    return ContextEnricher(container.llm, container.settings.ollama.llm_model)


def _write_report(options: LocalEvaluationOptions, summaries: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# Local evaluation",
        "",
        f"Split: {options.split}. Warmups excluded from measurements.",
        "",
        "| Arm | Cases | Failures | Outcome accuracy | Mean latency (s) | p95 (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, summary in summaries.items():
        lines.append(
            f"| {name} | {summary['case_count']} | {summary['failure_count']} | "
            f"{summary['outcome_accuracy']['rate']:.3f} | "
            f"{summary['latency']['mean_seconds']:.3f} | {summary['latency']['p95_seconds']:.3f} |"
        )
    lines.extend(
        [
            "",
            "See outputs.jsonl for per-case outputs and errors; "
            "metrics.json includes confidence intervals.",
            "This report measures this dataset and configuration only. "
            "A small synthetic dataset does not establish production targets.",
            "",
        ]
    )
    (options.output_directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
