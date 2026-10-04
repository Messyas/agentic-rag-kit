"""Immutable state carried through the corrective analysis workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from rag_kit.domain.analysis import GuardViolationInfo, Subject
from rag_kit.domain.models import Frozen, RetrievalQuery, ScoredChunk
from rag_kit.domain.ports.grader import GradeResult
from rag_kit.domain.ports.llm import LLMUsage


class WorkflowState(Frozen):
    subject: Subject
    run_id: str
    query: RetrievalQuery | None = None
    candidates: tuple[ScoredChunk, ...] = ()
    grade: GradeResult | None = None
    generated: BaseModel | None = None
    corrections_used: int = 0
    correction_log: tuple[str, ...] = ()
    violations: tuple[GuardViolationInfo, ...] = ()
    usage: LLMUsage = LLMUsage()
    repairs_used: int = 0
    trusted_numbers: dict[str, str] = Field(default_factory=dict)
