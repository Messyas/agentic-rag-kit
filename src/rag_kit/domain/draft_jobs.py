"""Portable draft job and human review states."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from rag_kit.domain.models import Frozen

JobState = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
ReviewState = Literal["PENDING_REVIEW", "NEEDS_INFORMATION", "ACCEPTED", "REJECTED", "STALE"]


class DraftJob(Frozen):
    job_id: str
    subject_id: str
    kind: Literal["review", "report"]
    fingerprint: str
    job_state: JobState
    review_state: ReviewState | None = None
    request_json: str
    result_json: str | None = None
    error: str | None = None
    attempts: int = Field(default=0, ge=0)
