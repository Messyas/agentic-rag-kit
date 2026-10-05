"""Period-close drafts use only trusted scope and metric snapshot values."""

from __future__ import annotations

import json

import pytest
from packs.scrap.assistant import ScrapAssistantFacade
from packs.scrap.assistant_schemas import (
    AccessScope,
    Evidence,
    MetricValue,
    PeriodScope,
    ReportRequest,
)
from pydantic import ValidationError

from rag_kit.domain.ports.llm import LLMRequest, LLMResponse


class EmptyLLM:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"context": [], "hypotheses": [], "gaps": []}), model=request.model
        )

    async def aclose(self) -> None:
        return


def _period_request() -> ReportRequest:
    observed = Evidence(
        source_id="occ-1",
        source_type="occurrence",
        version="v1",
        text="item_description: Chapa metálica\nrequisition_comment: Material recebido deformado",
        organization_code="F1",
        status="OBSERVED",
        occurrence_id="occ-1",
    )
    metric = Evidence(
        source_id="metric-1",
        source_type="metric",
        version="v2",
        text="Total de scrap calculado no snapshot",
        organization_code="F1",
        status="SNAPSHOT",
    )
    return ReportRequest(
        request_id="p1",
        expected_version=2,
        snapshot_id="snap-p1",
        access=AccessScope(
            organization_code="F1",
            allowed_source_ids=frozenset({"occ-1", "metric-1"}),
            access_revision="a1",
        ),
        sources=(observed, metric),
        report_id="rep-p1",
        report_kind="PERIOD_CLOSE",
        selected_occurrence_ids=("occ-1",),
        content_schema_version=2,
        scope=PeriodScope(period_from="2026-09-01", period_to="2026-09-30", currency="BRL"),
        metrics=(
            MetricValue(key="scrap_total", value="-125.40", unit="BRL", source_id="metric-1"),
        ),
    )


@pytest.mark.asyncio
async def test_metric_is_inserted_from_snapshot() -> None:
    draft = await ScrapAssistantFacade(EmptyLLM(), "test-local").draft_report(_period_request())
    summary = next(item for item in draft.suggestions if item.field == "executive_summary")
    assert "-125.40 BRL" in summary.text
    assert "metric-1" in summary.source_ids
    assert draft.gaps


def test_period_currency_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        ReportRequest.model_validate(
            {
                **_period_request().model_dump(mode="json"),
                "metrics": [
                    {"key": "scrap_total", "value": "10", "unit": "USD", "source_id": "metric-1"}
                ],
            }
        )
