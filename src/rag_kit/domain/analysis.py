"""Analysis entities and their explicit processing state machine."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from rag_kit.domain.errors import IllegalTransition
from rag_kit.domain.models import Frozen, SourceRef


class ProcessingState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class AnalysisOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


_ALLOWED = {
    ProcessingState.PENDING: frozenset({ProcessingState.RUNNING}),
    ProcessingState.RUNNING: frozenset(
        {ProcessingState.READY, ProcessingState.FAILED, ProcessingState.STALE}
    ),
    ProcessingState.FAILED: frozenset({ProcessingState.PENDING}),
    ProcessingState.STALE: frozenset({ProcessingState.PENDING}),
    ProcessingState.READY: frozenset({ProcessingState.STALE}),
}


def transition(current: ProcessingState, target: ProcessingState) -> ProcessingState:
    if target not in _ALLOWED[current]:
        raise IllegalTransition(f"{current} -> {target} is not allowed")  # noqa: TRY003
    return target


class Subject(Frozen):
    subject_id: str
    kind: str
    fields: dict[str, Any] = Field(default_factory=dict)
    version: str = "1"

    def idempotency_key(self, pipeline_version: str) -> str:
        value = f"{self.subject_id}|{self.version}|{pipeline_version}".encode()
        return hashlib.sha256(value).hexdigest()


class Claim(Frozen):
    kind: Literal["fact", "context", "hypothesis"]
    statement: str
    source_ids: tuple[str, ...] = ()


class Gap(Frozen):
    question: str
    evidence_needed: str | None = None


class GuardViolationInfo(Frozen):
    guard: str
    code: str
    message: str
    path: str | None = None


class AnalysisResult(Frozen):
    subject_id: str
    subject_version: str = "1"
    outcome: AnalysisOutcome
    claims: tuple[Claim, ...] = ()
    gaps: tuple[Gap, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)
    violations: tuple[GuardViolationInfo, ...] = ()
    run_id: str = ""
    pipeline_version: str = "1"
    usage: dict[str, Any] = Field(default_factory=dict)
    source_refs: tuple[SourceRef, ...] = ()
