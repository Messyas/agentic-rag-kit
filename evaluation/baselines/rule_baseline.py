"""Deterministic lexical baseline used to measure the value of agentic RAG."""

from __future__ import annotations

from typing import TYPE_CHECKING

from packs.scrap.schemas import deterministic_facts

from rag_kit.domain.analysis import AnalysisOutcome, AnalysisResult, Claim, Gap, Subject
from rag_kit.domain.models import RetrievalQuery

if TYPE_CHECKING:
    from rag_kit.domain.ports.retriever import Retriever


class RuleBaseline:
    """Use lexical retrieval and a score threshold without invoking an LLM."""

    def __init__(self, retriever: Retriever, threshold: float = 0.15) -> None:
        if threshold < 0:
            raise ValueError("threshold must be non-negative")  # noqa: TRY003
        self._retriever = retriever
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "rule_baseline"

    @property
    def version(self) -> str:
        return "1"

    async def analyze(self, subject: Subject) -> AnalysisResult:
        text = " ".join(str(value) for value in subject.fields.values() if value)
        matches = await self._retriever.retrieve(
            RetrievalQuery(text=text, k=3, source_types=("scrap_review",))
        )
        strong_matches = [match for match in matches if match.score >= self._threshold]
        claims = list(deterministic_facts(subject))
        if strong_matches:
            top_match = strong_matches[0]
            claims.append(
                Claim(
                    kind="context",
                    statement=top_match.chunk.content[:400],
                    source_ids=(top_match.chunk.ref.source_id,),
                )
            )
            outcome = AnalysisOutcome.COMPLETE
            gaps: tuple[Gap, ...] = ()
        else:
            outcome = AnalysisOutcome.INSUFFICIENT_EVIDENCE
            gaps = (Gap(question="Qual análise revisada pode confirmar a causa da ocorrência?"),)
        return AnalysisResult(
            subject_id=subject.subject_id,
            outcome=outcome,
            claims=tuple(claims),
            gaps=gaps,
            payload={"baseline": self.name, "observed_fields": subject.fields},
        )
