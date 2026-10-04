"""Deterministic relevance grading with explicitly configured thresholds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_kit.domain.ports.grader import ChunkGrade, GradeResult, Verdict

if TYPE_CHECKING:
    from rag_kit.domain.models import ScoredChunk


class ScoreGrader:
    def __init__(self, threshold: float = 0.0, minimum_relevant: int = 1) -> None:
        self._threshold = threshold
        self._minimum = minimum_relevant

    async def grade(self, query: str, candidates: tuple[ScoredChunk, ...]) -> GradeResult:  # noqa: ARG002 - port signature retained
        grades = tuple(
            ChunkGrade(
                chunk_id=item.chunk.chunk_id,
                score=item.score,
                verdict=Verdict.RELEVANT if item.score > self._threshold else Verdict.IRRELEVANT,
            )
            for item in candidates
        )
        return GradeResult(
            sufficient=sum(grade.verdict == Verdict.RELEVANT for grade in grades) >= self._minimum,
            grades=grades,
        )


class NullGrader:
    async def grade(self, query: str, candidates: tuple[ScoredChunk, ...]) -> GradeResult:  # noqa: ARG002 - port signature retained
        return GradeResult(
            sufficient=bool(candidates),
            grades=tuple(
                ChunkGrade(chunk_id=item.chunk.chunk_id, score=item.score, verdict=Verdict.RELEVANT)
                for item in candidates
            ),
        )
