"""Evidence relevance and sufficiency grading boundary."""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from rag_kit.domain.models import ScoredChunk


class Verdict(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    INSUFFICIENT = "insufficient"


class ChunkGrade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chunk_id: str
    verdict: Verdict
    score: float
    rationale: str = ""


class GradeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sufficient: bool
    grades: tuple[ChunkGrade, ...] = ()
    rationale: str = ""

    @property
    def relevant_chunks(self) -> tuple[str, ...]:
        return tuple(grade.chunk_id for grade in self.grades if grade.verdict == Verdict.RELEVANT)


@runtime_checkable
class Grader(Protocol):
    async def grade(self, query: str, candidates: tuple[ScoredChunk, ...]) -> GradeResult: ...
