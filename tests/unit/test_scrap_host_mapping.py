"""Ensure accepted drafts map to Hanaro-compatible update commands."""

from __future__ import annotations

import pytest
from packs.scrap.assistant_schemas import AssistantDraft, DraftSuggestion
from packs.scrap.host_mapping import (
    report_sections_payload,
    report_update_payload,
    review_write_payload,
)


def _draft(*suggestions: DraftSuggestion) -> AssistantDraft:
    return AssistantDraft(
        request_id="r1",
        subject_id="s1",
        expected_version=3,
        snapshot_fingerprint="abc",
        outcome="COMPLETE",
        suggestions=suggestions,
    )


def test_review_mapping_keeps_cause_as_hypothesis() -> None:
    payload = review_write_payload(
        _draft(
            DraftSuggestion(field="title", text="Título"),
            DraftSuggestion(field="description", text="Descrição sustentada"),
            DraftSuggestion(field="cause_family", text="MACHINE", source_ids=("rev1",)),
            DraftSuggestion(
                field="cause_description", text="Possível ajuste", source_ids=("rev1",)
            ),
        )
    )
    assert payload["expected_version"] == 3
    assert payload["cause_family"] == "MACHINE"
    assert payload["cause_certainty"] == "HYPOTHESIS"
    assert "defect_type_id" not in payload


def test_sections_mapping_preserves_other_sections() -> None:
    draft = _draft(
        DraftSuggestion(field="CONTEXT", text="Contexto novo"),
        DraftSuggestion(field="executive_summary", text="Resumo"),
    )
    original = [
        {
            "id": "internal",
            "section_key": "context",
            "kind": "CONTEXT",
            "payload": {"text": "Antigo", "note": "x"},
        },
        {"section_key": "kpi", "kind": "KPI", "payload": {"value": "10"}},
    ]
    sections = report_sections_payload(draft, original, expected_version=3)
    assert sections["sections"][0]["payload"] == {"text": "Contexto novo", "note": "x"}
    assert "id" not in sections["sections"][0]
    assert sections["sections"][1] == original[1]
    assert sections["expected_version"] == 3
    assert report_update_payload(draft)["executive_summary"] == "Resumo"


def test_sections_mapping_rejects_stale_version() -> None:
    draft = _draft(DraftSuggestion(field="CONTEXT", text="Contexto novo"))
    with pytest.raises(ValueError, match="stale"):
        report_sections_payload(
            draft, [{"section_key": "context", "payload": {}}], expected_version=4
        )


def test_incomplete_draft_cannot_be_mapped() -> None:
    incomplete = _draft().model_copy(update={"outcome": "INSUFFICIENT_EVIDENCE"})
    with pytest.raises(ValueError, match="insufficient draft"):
        report_update_payload(incomplete)
