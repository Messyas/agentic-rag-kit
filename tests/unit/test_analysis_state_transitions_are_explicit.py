"""Processing transitions reject paths outside the declared state machine."""

import pytest

from rag_kit.domain.analysis import ProcessingState, Subject, transition
from rag_kit.domain.errors import IllegalTransition


def test_analysis_state_transition_accepts_and_rejects_edges() -> None:
    assert transition(ProcessingState.PENDING, ProcessingState.RUNNING) == ProcessingState.RUNNING
    with pytest.raises(IllegalTransition):
        transition(ProcessingState.PENDING, ProcessingState.READY)


def test_subject_idempotency_key_changes_with_pipeline_version() -> None:
    subject = Subject(subject_id="OC-1", kind="scrap", version="2")

    assert subject.idempotency_key("1") == subject.idempotency_key("1")
    assert subject.idempotency_key("1") != subject.idempotency_key("2")
