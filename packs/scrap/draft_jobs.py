"""Automatic generation jobs composed from host snapshots."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol

from packs.scrap.assistant import ScrapAssistantFacade, snapshot_fingerprint
from packs.scrap.assistant_schemas import ReportRequest, ReviewRequest

from rag_kit.domain.draft_jobs import DraftJob

if TYPE_CHECKING:
    from collections.abc import Sequence


class DraftQueue(Protocol):
    def enqueue(self, job: DraftJob) -> DraftJob: ...
    def claim(self) -> DraftJob | None: ...
    def finish(self, job_id: str, result_json: str, *, needs_information: bool) -> DraftJob: ...
    def fail(self, job_id: str, error: str) -> DraftJob: ...


class DraftJobService:
    def __init__(self, queue: DraftQueue, assistant: ScrapAssistantFacade | None = None) -> None:
        self._queue = queue
        self._assistant = assistant

    def enqueue(self, request: ReviewRequest | ReportRequest) -> DraftJob:
        kind = "review" if isinstance(request, ReviewRequest) else "report"
        subject_id = (
            request.occurrence_id if isinstance(request, ReviewRequest) else request.report_id
        )
        fingerprint = (
            self._assistant.generation_fingerprint(request)
            if self._assistant is not None
            else snapshot_fingerprint(request)
        )
        job_id = hashlib.sha256(f"{subject_id}|{kind}|{fingerprint}".encode()).hexdigest()[:32]
        return self._queue.enqueue(
            DraftJob(
                job_id=job_id,
                subject_id=subject_id,
                kind=kind,
                fingerprint=fingerprint,
                job_state="QUEUED",
                request_json=request.model_dump_json(),
            )
        )

    def enqueue_batch(
        self, requests: Sequence[ReviewRequest | ReportRequest]
    ) -> tuple[DraftJob, ...]:
        return tuple(self.enqueue(request) for request in requests)

    async def process_one(self) -> DraftJob | None:
        if self._assistant is None:
            raise RuntimeError("draft generator is not configured")  # noqa: TRY003
        job = self._queue.claim()
        if job is None:
            return None
        try:
            if job.kind == "review":
                result = await self._assistant.suggest_review(
                    ReviewRequest.model_validate_json(job.request_json)
                )
            else:
                result = await self._assistant.draft_report(
                    ReportRequest.model_validate_json(job.request_json)
                )
        except Exception as error:
            return self._queue.fail(job.job_id, type(error).__name__)
        return self._queue.finish(
            job.job_id,
            result.model_dump_json(),
            needs_information=result.outcome == "INSUFFICIENT_EVIDENCE",
        )
