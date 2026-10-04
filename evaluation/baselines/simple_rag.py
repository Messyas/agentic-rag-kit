"""Simple retrieval and guarded generation without grading or corrections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_kit.application.generation.output_guard import (
    AbstentionGuard,
    GuardChain,
    HypothesisLabelGuard,
    InjectionEchoGuard,
    NumberParityGuard,
    SourceExistsGuard,
)
from rag_kit.application.grading.score_grader import NullGrader
from rag_kit.application.workflow.corrections import CorrectionPlanner
from rag_kit.application.workflow.corrective_rag import CorrectiveRagPipeline
from rag_kit.application.workflow.nodes import RunContext
from rag_kit.application.workflow.policies import WorkflowPolicy
from rag_kit.domain.ports.tracer import NullTracer

if TYPE_CHECKING:
    from rag_kit.application.generation.generator import StructuredGenerator
    from rag_kit.application.pack import PackSpec
    from rag_kit.domain.analysis import AnalysisResult, Subject
    from rag_kit.domain.ports.retriever import Retriever


class SimpleRagBaseline:
    def __init__(
        self, retriever: Retriever, generator: StructuredGenerator, pack: PackSpec
    ) -> None:
        guards = GuardChain(
            (
                SourceExistsGuard(),
                NumberParityGuard(),
                AbstentionGuard(),
                HypothesisLabelGuard(),
                InjectionEchoGuard(),
                *pack.guards(),
            )
        )
        context = RunContext(pack, retriever, NullGrader(), generator, guards, NullTracer())
        self._pipeline = CorrectiveRagPipeline(
            context, CorrectionPlanner(()), WorkflowPolicy(max_corrections=0)
        )

    @property
    def name(self) -> str:
        return "simple_rag"

    @property
    def version(self) -> str:
        return "1"

    async def analyze(self, subject: Subject) -> AnalysisResult:
        return await self._pipeline.analyze(subject)
