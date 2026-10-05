"""Verify grounded drafts and automatic review queue behavior."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from packs.scrap.assistant import ScrapAssistantFacade
from packs.scrap.assistant_schemas import AccessScope, Evidence, ReportRequest, ReviewRequest
from packs.scrap.draft_jobs import DraftJobService
from pydantic import ValidationError

from rag_kit.domain.ports.llm import LLMRequest, LLMResponse
from rag_kit.infrastructure.persistence.draft_queue import SqliteDraftQueue

if TYPE_CHECKING:
    from pathlib import Path


class FakeLLM:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=json.dumps(self.output), model=request.model)

    async def aclose(self) -> None:
        return


def _source() -> Evidence:
    return Evidence(
        source_id="review-1",
        source_type="scrap_review",
        version="2",
        text="Analista registrou falha no ajuste da máquina e recomendou verificar o torque.",
        organization_code="F1",
        status="REVIEWED",
        occurrence_id="occ-1",
    )


def _access() -> AccessScope:
    return AccessScope(
        organization_code="F1", allowed_source_ids=frozenset({"review-1"}), access_revision="a1"
    )


def _review(source: Evidence) -> ReviewRequest:
    return ReviewRequest(
        request_id="r1",
        expected_version=1,
        snapshot_id="snap-1",
        access=_access(),
        sources=(source,),
        occurrence_id="occ-1",
        occurrence={"item_description": "peça", "requisition_comment": "scrap"},
    )


def _output() -> dict[str, object]:
    return {
        "context": [
            {
                "statement": "Foi registrada uma falha no ajuste da máquina.",
                "source_id": "review-1",
                "quote": "falha no ajuste da máquina",
            }
        ],
        "hypotheses": [
            {
                "family": "MACHINE",
                "statement": "Possível problema de ajuste da máquina.",
                "source_id": "review-1",
                "quote": "falha no ajuste da máquina",
                "next_check": "Verificar torque com manutenção.",
            }
        ],
        "gaps": [],
    }


@pytest.mark.asyncio
async def test_review_draft_uses_cited_evidence_and_four_m() -> None:
    llm = FakeLLM(_output())
    draft = await ScrapAssistantFacade(llm, "test-local").suggest_review(_review(_source()))
    assert draft.outcome == "COMPLETE"
    assert draft.four_m[1].family == "MACHINE"
    assert draft.four_m[1].certainty == "HYPOTHESIS"
    assert all(item.certainty == "UNASSESSED" for item in draft.four_m if item.family != "MACHINE")
    assert any(suggestion.field == "cause_family" for suggestion in draft.suggestions)
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_uncited_or_numeric_claims_are_removed() -> None:
    output = _output()
    output["context"] = [
        {"statement": "Custo de 999 reais informado.", "source_id": "review-1", "quote": "falha"}
    ]
    output["hypotheses"] = [
        {
            "family": "MACHINE",
            "statement": "Causa confirmada sem prova.",
            "source_id": "review-1",
            "quote": "trecho inexistente",
            "next_check": "Verificar a fonte.",
        }
    ]
    draft = await ScrapAssistantFacade(FakeLLM(output), "test-local").suggest_review(
        _review(_source())
    )
    assert draft.outcome == "INSUFFICIENT_EVIDENCE"
    assert not draft.claims
    assert all(item.certainty == "UNASSESSED" for item in draft.four_m)
    assert draft.gaps


@pytest.mark.asyncio
async def test_other_occurrence_cause_cannot_be_stated_as_current_cause() -> None:
    source = _source().model_copy(update={"occurrence_id": "another-case"})
    draft = await ScrapAssistantFacade(FakeLLM(_output()), "test-local").suggest_review(
        _review(source)
    )
    assert draft.outcome == "INSUFFICIENT_EVIDENCE"
    assert all(item.certainty == "UNASSESSED" for item in draft.four_m)


def test_access_and_report_kind_are_enforced() -> None:
    with pytest.raises(ValidationError):
        _review(_source().model_copy(update={"organization_code": "F2"}))
    with pytest.raises(ValidationError):
        ReportRequest(
            request_id="r2",
            expected_version=1,
            snapshot_id="snap-2",
            access=_access(),
            sources=(_source(),),
            report_id="rep-1",
            report_kind="PERIOD_CLOSE",
            selected_occurrence_ids=("occ-1",),
        )


@pytest.mark.asyncio
async def test_batch_jobs_are_idempotent_and_reviewable(tmp_path: Path) -> None:
    queue = SqliteDraftQueue(tmp_path / "drafts.sqlite3")
    service = DraftJobService(queue, ScrapAssistantFacade(FakeLLM(_output()), "test-local"))
    request = _review(_source())
    first = service.enqueue(request)
    assert service.enqueue(request).job_id == first.job_id
    result = await service.process_one()
    assert result is not None
    assert result.review_state == "PENDING_REVIEW"
    assert await service.process_one() is None
    assert queue.review(first.job_id, "ACCEPTED").review_state == "ACCEPTED"
    assert len(queue.list()) == 1
    revised = request.model_copy(update={"snapshot_id": "snap-2"})
    assert service.enqueue(revised).job_id != first.job_id
    assert service.enqueue(request).job_id == first.job_id
    assert queue.get(service.enqueue(revised).job_id).job_state == "QUEUED"


@pytest.mark.asyncio
async def test_old_running_job_becomes_stale_when_new_snapshot_arrives(tmp_path: Path) -> None:
    queue = SqliteDraftQueue(tmp_path / "drafts.sqlite3")
    service = DraftJobService(queue, ScrapAssistantFacade(FakeLLM(_output()), "test-local"))
    old = service.enqueue(_review(_source()))
    running = queue.claim()
    assert running is not None
    new = service.enqueue(_review(_source()).model_copy(update={"snapshot_id": "new"}))
    assert new.job_id != old.job_id
    finished = queue.finish(old.job_id, "{}", needs_information=False)
    assert finished.review_state == "STALE"
    with pytest.raises(ValueError, match="not reviewable"):
        queue.review(old.job_id, "ACCEPTED")


@pytest.mark.asyncio
async def test_insufficient_draft_cannot_be_accepted(tmp_path: Path) -> None:
    queue = SqliteDraftQueue(tmp_path / "drafts.sqlite3")
    empty_output = {"context": [], "hypotheses": [], "gaps": []}
    assistant = ScrapAssistantFacade(FakeLLM(empty_output), "test-local")
    service = DraftJobService(queue, assistant)
    queued = service.enqueue(_review(_source()))
    completed = await service.process_one()
    assert completed is not None
    assert completed.job_id == queued.job_id
    assert completed.review_state == "NEEDS_INFORMATION"
    with pytest.raises(ValueError, match="insufficient draft"):
        queue.review(queued.job_id, "ACCEPTED")
