"""Behavioral checks for reusable composition, guarded generation and host inputs."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from packs.scrap import build_pack, subject_from_record
from packs.scrap.metrics_csv import CsvMetricsAdapter
from packs.scrap.schemas import build_pre_analysis_model
from tests.fakes import FakeLLM, HashEmbedder, InMemoryVectorStore

from rag_kit.application.facade import AnalysisFacade, FacadeDependencies
from rag_kit.application.generation.generator import (
    RunnerOptions,
    StructuredGenerator,
    StructuredOutputRunner,
)
from rag_kit.application.generation.output_guard import (
    AbstentionGuard,
    GuardChain,
    NumberParityGuard,
    SourceExistsGuard,
)
from rag_kit.application.generation.prompt_builder import PromptBuilder
from rag_kit.application.generation.prompt_registry import PromptRegistry
from rag_kit.application.grading.score_grader import ScoreGrader
from rag_kit.application.retrieval.lexical import LexicalRetriever
from rag_kit.application.workflow.corrections import CorrectionPlanner, IncreaseK
from rag_kit.application.workflow.corrective_rag import CorrectiveRagPipeline
from rag_kit.application.workflow.nodes import RunContext
from rag_kit.application.workflow.policies import WorkflowPolicy
from rag_kit.domain.analysis import AnalysisOutcome, Subject
from rag_kit.domain.models import Document, SourceRef
from rag_kit.domain.ports.llm import LLMResponse
from rag_kit.domain.ports.tracer import NullTracer


def _output(source: str = "R1", value: str = "-14.41") -> LLMResponse:
    return LLMResponse(
        model="fake",
        content=json.dumps(
            {
                "outcome": "complete",
                "context": [
                    {
                        "statement": "Transport damage confirmed by the review.",
                        "source_ids": [source],
                    }
                ],
                "figures": [{"label": "cost", "value": value, "unit": "BRL"}],
            }
        ),
    )


def _facade(responses: list[LLMResponse], pack=None) -> tuple[AnalysisFacade, FakeLLM]:
    pack = pack or build_pack()
    pack.validate()
    llm = FakeLLM(responses)
    store = InMemoryVectorStore()
    retriever = LexicalRetriever(store)
    embedder = HashEmbedder()
    generator = StructuredGenerator(
        PromptBuilder(PromptRegistry(pack.prompts_dir)),
        StructuredOutputRunner(llm, RunnerOptions("fake")),
        pack,
    )
    context = RunContext(
        pack,
        retriever,
        ScoreGrader(),
        generator,
        GuardChain((SourceExistsGuard(), NumberParityGuard(), AbstentionGuard())),
        NullTracer(),
    )
    pipeline = CorrectiveRagPipeline(context, CorrectionPlanner((IncreaseK(),)), WorkflowPolicy())
    return AnalysisFacade(FacadeDependencies(pack, pipeline, retriever, store, embedder)), llm


async def _index(facade: AnalysisFacade) -> None:
    await facade.index_documents(
        [
            Document(
                ref=SourceRef(source_type="scrap_review", source_id="R1"),
                text="transport panel damage",
                metadata={"source_type": "scrap_review"},
            )
        ]
    )


async def test_facade_generates_source_backed_analysis() -> None:
    facade, llm = _facade([_output()])
    await _index(facade)
    result = await facade.analyze(
        Subject(
            subject_id="O1",
            kind="scrap",
            fields={"erp_comment": "transport panel damage", "cost": "-14.41"},
        )
    )
    assert result.outcome == AnalysisOutcome.COMPLETE
    assert result.claims[-1].source_ids == ("R1",)
    assert result.payload["figures"][0]["value"] == "-14.41"
    assert len(llm.requests) == 1


async def test_missing_evidence_abstains_without_generation() -> None:
    facade, llm = _facade([])
    result = await facade.analyze(Subject(subject_id="O1", kind="scrap", fields={"quantity": "-2"}))
    assert result.outcome == AnalysisOutcome.INSUFFICIENT_EVIDENCE
    assert result.gaps
    assert not llm.requests
    assert all(claim.kind == "fact" for claim in result.claims)


async def test_unknown_sources_trigger_one_guard_repair() -> None:
    facade, llm = _facade([_output("fabricated"), _output()])
    await _index(facade)
    result = await facade.analyze(
        Subject(
            subject_id="O1",
            kind="scrap",
            fields={"erp_comment": "transport panel damage", "cost": "-14.41"},
        )
    )
    assert result.outcome == AnalysisOutcome.COMPLETE
    assert len(llm.requests) == 2


async def test_persisting_guard_errors_produce_abstention() -> None:
    facade, llm = _facade([_output(value="14.41"), _output(value="14.41")])
    await _index(facade)
    result = await facade.analyze(
        Subject(
            subject_id="O1",
            kind="scrap",
            fields={"erp_comment": "transport panel damage", "cost": "-14.41"},
        )
    )
    assert result.outcome == AnalysisOutcome.INSUFFICIENT_EVIDENCE
    assert result.violations[0].code == "figure_mismatch"
    assert len(llm.requests) == 2


async def test_schema_repair_aggregates_all_usage() -> None:
    llm = FakeLLM([LLMResponse(content="not JSON", model="fake"), _output()])
    runner = StructuredOutputRunner(llm, RunnerOptions("fake"))
    output = await runner.run([], build_pre_analysis_model())
    assert output.repairs_used == 1
    assert len(llm.requests) == 2


def test_host_records_preserve_identity_and_decimals() -> None:
    subject = subject_from_record(
        {
            "occurrence_id": "uuid-1",
            "organization_code": "NW4",
            "issue_amount_brl": "-1969.87",
            "issue_quantity": "-5",
            "content_hash": "revision-a",
        }
    )
    assert subject.fields["cost"] == "-1969.87"
    assert subject.fields["factory"] == "NW4"
    assert subject.version == "revision-a"
    with pytest.raises(Exception, match="occurrence_id"):
        subject_from_record({"item_code": "001"})


async def test_metrics_do_not_sum_transaction_versions() -> None:
    records = [
        {"occurrence_id": "O1", "issue_amount_brl": "-10.01", "issue_quantity": "-1"},
        {"occurrence_id": "O1", "issue_amount_brl": "-20.02", "issue_quantity": "-2"},
    ]
    summary = await CsvMetricsAdapter(records).summary({})
    assert summary.n_occurrences == 1
    assert summary.total_cost == Decimal("-20.02")


async def test_different_domain_pack_uses_same_kernel() -> None:
    # The application depends on PackSpec, not on the scrap implementation.
    pack = replace(
        build_pack(),
        name="maintenance",
        subject_from_record=lambda record: Subject(
            subject_id=record["asset_id"], kind="maintenance", fields=record
        ),
    )
    generic, _llm = _facade([_output()], pack)
    await _index(generic)
    result = await generic.analyze_record(
        {"asset_id": "A1", "erp_comment": "transport panel damage", "cost": "-14.41"}
    )
    assert result.subject_id == "A1"
    assert result.outcome == AnalysisOutcome.COMPLETE
