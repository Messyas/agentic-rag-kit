"""Content-free analysis lifecycle events for host subscribers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisStarted:
    run_id: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class AnalysisFinished:
    run_id: str
    subject_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class AnalysisFailed:
    run_id: str
    subject_id: str
    error_type: str
