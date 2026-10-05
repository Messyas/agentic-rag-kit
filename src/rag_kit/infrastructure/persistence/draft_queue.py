"""SQLite-backed local draft queue; hosts may replace it with their own adapter."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rag_kit.domain.draft_jobs import DraftJob, ReviewState

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path


class SqliteDraftQueue:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS draft_jobs (
                job_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL,
                kind TEXT NOT NULL, fingerprint TEXT NOT NULL,
                job_state TEXT NOT NULL, review_state TEXT,
                request_json TEXT NOT NULL, result_json TEXT,
                error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(subject_id, kind, fingerprint)
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS draft_jobs_subject ON draft_jobs(subject_id, kind)"
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _job(row: sqlite3.Row) -> DraftJob:
        return DraftJob.model_validate(dict(row))

    def enqueue(self, job: DraftJob) -> DraftJob:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM draft_jobs WHERE subject_id=? AND kind=? AND fingerprint=?",
                (job.subject_id, job.kind, job.fingerprint),
            ).fetchone()
            if existing is not None:
                return self._job(existing)
            db.execute(
                "INSERT INTO draft_jobs "
                "(job_id, subject_id, kind, fingerprint, job_state, "
                "review_state, request_json, attempts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.subject_id,
                    job.kind,
                    job.fingerprint,
                    job.job_state,
                    job.review_state,
                    job.request_json,
                    job.attempts,
                ),
            )
            row = db.execute(
                "SELECT * FROM draft_jobs WHERE subject_id=? AND kind=? AND fingerprint=?",
                (job.subject_id, job.kind, job.fingerprint),
            ).fetchone()
            db.execute(
                "UPDATE draft_jobs SET review_state='STALE' "
                "WHERE subject_id=? AND kind=? AND job_id<>? "
                "AND review_state IN ('PENDING_REVIEW', 'NEEDS_INFORMATION')",
                (job.subject_id, job.kind, job.job_id),
            )
        if row is None:
            raise RuntimeError("queued job disappeared")  # noqa: TRY003
        return self._job(row)

    def claim(self) -> DraftJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM draft_jobs WHERE job_state='QUEUED' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE draft_jobs SET job_state='RUNNING', attempts=attempts+1 WHERE job_id=?",
                (row["job_id"],),
            )
            running = db.execute(
                "SELECT * FROM draft_jobs WHERE job_id=?", (row["job_id"],)
            ).fetchone()
        return self._job(running)

    def finish(self, job_id: str, result_json: str, *, needs_information: bool) -> DraftJob:
        state = "NEEDS_INFORMATION" if needs_information else "PENDING_REVIEW"
        with self._connect() as db:
            current = db.execute(
                "SELECT rowid, subject_id, kind FROM draft_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if current is None:
                raise KeyError(job_id)
            newer = db.execute(
                "SELECT 1 FROM draft_jobs WHERE subject_id=? AND kind=? AND rowid>? LIMIT 1",
                (current["subject_id"], current["kind"], current["rowid"]),
            ).fetchone()
            if newer is not None:
                state = "STALE"
            cursor = db.execute(
                "UPDATE draft_jobs SET job_state='COMPLETED', review_state=?, "
                "result_json=?, error=NULL "
                "WHERE job_id=? AND job_state='RUNNING'",
                (state, result_json, job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("job is not running")  # noqa: TRY003
        return self.get(job_id)

    def fail(self, job_id: str, error: str) -> DraftJob:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE draft_jobs SET job_state='FAILED', error=? "
                "WHERE job_id=? AND job_state='RUNNING'",
                (error[:500], job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("job is not running")  # noqa: TRY003
        return self.get(job_id)

    def retry(self, job_id: str, max_attempts: int = 2) -> DraftJob:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE draft_jobs SET job_state='QUEUED', error=NULL "
                "WHERE job_id=? AND job_state='FAILED' AND attempts<?",
                (job_id, max_attempts),
            )
            if cursor.rowcount != 1:
                raise ValueError("job cannot be retried")  # noqa: TRY003
        return self.get(job_id)

    def review(self, job_id: str, decision: ReviewState) -> DraftJob:
        if decision not in {"ACCEPTED", "REJECTED", "NEEDS_INFORMATION"}:
            raise ValueError("unsupported review decision")  # noqa: TRY003
        with self._connect() as db:
            row = db.execute(
                "SELECT result_json FROM draft_jobs WHERE job_id=? AND job_state='COMPLETED' "
                "AND review_state IN ('PENDING_REVIEW','NEEDS_INFORMATION')",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ValueError("job is not reviewable")  # noqa: TRY003
            if decision == "ACCEPTED" and row["result_json"]:
                result = json.loads(row["result_json"])
                if result.get("outcome") != "COMPLETE":
                    raise ValueError("insufficient draft cannot be accepted")  # noqa: TRY003
            cursor = db.execute(
                "UPDATE draft_jobs SET review_state=? WHERE job_id=? AND job_state='COMPLETED' "
                "AND review_state IN ('PENDING_REVIEW','NEEDS_INFORMATION')",
                (decision, job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("job is not reviewable")  # noqa: TRY003
        return self.get(job_id)

    def get(self, job_id: str) -> DraftJob:
        with self._connect() as db:
            row = db.execute("SELECT * FROM draft_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job(row)

    def list(self, review_state: ReviewState | None = None) -> Sequence[DraftJob]:
        with self._connect() as db:
            if review_state is None:
                rows = db.execute("SELECT * FROM draft_jobs ORDER BY rowid").fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM draft_jobs WHERE review_state=? ORDER BY rowid",
                    (review_state,),
                ).fetchall()
        return tuple(self._job(row) for row in rows)
