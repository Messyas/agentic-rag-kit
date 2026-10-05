"""Regression checks for evidence scoring and stratified real-data sampling."""

from __future__ import annotations

from decimal import Decimal

import pytest
from evaluation.hanaro_draft_eval import _checks, _sample_indices
from packs.scrap.assistant_schemas import (
    AccessScope,
    AssistantDraft,
    Evidence,
    FourMItem,
    ReportRequest,
    ReviewRequest,
    SupportedStatement,
)


def _request() -> ReviewRequest:
    source = Evidence(
        source_id="source:one",
        source_type="occurrence",
        version="v1",
        text="Comentário de origem: scrap sem análise de causa.",
        organization_code="F1",
        status="OBSERVED",
        occurrence_id="occ-1",
    )
    return ReviewRequest(
        request_id="test-1",
        expected_version=1,
        snapshot_id="snap-1",
        access=AccessScope(
            organization_code="F1",
            allowed_source_ids=frozenset({source.source_id}),
            access_revision="a1",
        ),
        sources=(source,),
        occurrence_id="occ-1",
        occurrence={},
    )


def _draft() -> AssistantDraft:
    return AssistantDraft(
        request_id="test-1",
        subject_id="occ-1",
        expected_version=1,
        snapshot_fingerprint="hash",
        outcome="INSUFFICIENT_EVIDENCE",
        claims=(
            SupportedStatement(
                statement="A origem registra scrap sem análise de causa.",
                source_id="source:one",
                quote="scrap sem análise de causa",
            ),
        ),
        source_refs=("occurrence:source:one@v1",),
    )


def test_literal_evidence_with_colons_in_source_id_scores_correctly() -> None:
    score = _checks(_draft(), _request())
    assert score["citation_ids_valid"]
    assert score["claim_quotes_literal"]
    assert score["source_scope_valid"]


def test_exact_transaction_fields_are_scored_independently_from_cause_claims() -> None:
    request = _request()
    source = request.sources[0].model_copy(
        update={
            "text": (
                "item_description: Peça metálica\n"
                "requisition_comment: Quebra após montagem"
            )
        }
    )
    request = request.model_copy(update={"sources": (source,)})
    draft = _draft().model_copy(
        update={
            "claims": (
                SupportedStatement(
                    statement="Item registrado: Peça metálica",
                    source_id=source.source_id,
                    quote="Peça metálica",
                ),
                SupportedStatement(
                    statement="Observação de origem: Quebra após montagem",
                    source_id=source.source_id,
                    quote="Quebra após montagem",
                ),
            )
        }
    )
    score = _checks(draft, request)
    assert score["field_tp"] == 2
    assert score["field_fp"] == 0
    assert score["field_fn"] == 0
    assert score["field_f1"] == 1.0


@pytest.mark.parametrize(
    ("source_id", "quote"),
    [("missing-source", "scrap sem análise de causa"), ("source:one", "máquina defeituosa")],
)
def test_fabricated_evidence_fails_literal_check(source_id: str, quote: str) -> None:
    claim = _draft().claims[0].model_copy(update={"source_id": source_id, "quote": quote})
    draft = _draft().model_copy(update={"claims": (claim,)})
    assert not _checks(draft, _request())["claim_quotes_literal"]


def test_wrong_source_version_fails_reference_check() -> None:
    draft = _draft().model_copy(update={"source_refs": ("occurrence:source:one@v2",)})
    assert not _checks(draft, _request())["citation_ids_valid"]


def test_transaction_only_source_cannot_score_as_confirmed_cause() -> None:
    item = FourMItem(
        family="MACHINE",
        hypothesis="Possível falha de máquina.",
        observation="scrap sem análise de causa",
        certainty="CONFIRMED",
        source_ids=("source:one",),
    )
    draft = _draft().model_copy(update={"four_m": (item,)})
    assert not _checks(draft, _request())["no_cause_marked_confirmed"]


def test_report_using_unselected_occurrence_fails_scope_check() -> None:
    review = _request()
    report = ReportRequest(
        request_id=review.request_id,
        expected_version=1,
        snapshot_id=review.snapshot_id,
        access=review.access,
        sources=review.sources,
        report_id="report-1",
        report_kind="DOSSIER",
        selected_occurrence_ids=("different-occurrence",),
    )
    assert not _checks(_draft(), report)["source_scope_valid"]


def test_sample_is_repeatable_unique_and_covers_strata() -> None:
    rows = tuple(
        {
            "organization_code": org,
            "issue_amount_brl": amount,
            "requisition_comment": comment,
        }
        for org in ("F1", "F2")
        for amount in (Decimal("-1.25"), Decimal("0"))
        for comment in ("", "scrap")
        for _ in range(3)
    )
    sample = _sample_indices(rows, 8)
    assert sample == _sample_indices(rows, 8)
    assert len(set(sample)) == 8
    assert len({tuple(rows[index].values()) for index in sample}) == 8
    assert len(_sample_indices(rows, 100)) == len(rows)


def test_sampling_empty_data_returns_no_cases() -> None:
    assert _sample_indices((), 5) == ()


def test_sampling_rejects_nonpositive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        _sample_indices((), 0)
