"""Versioned host-facing contracts for scrap draft generation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from rag_kit.domain.models import Frozen

_MIN_PERIOD_CLOSE_SCHEMA = 2

FourM = Literal["MAN", "MACHINE", "METHOD", "MATERIAL"]
CauseFamily = Literal["MAN", "MACHINE", "METHOD", "MATERIAL", "OTHER"]
ReportKind = Literal["DOSSIER", "PERIOD_CLOSE"]


class Evidence(Frozen):
    source_id: str = Field(min_length=1)
    source_type: Literal["scrap_review", "report", "occurrence", "metric"]
    version: str = Field(min_length=1)
    text: str = Field(min_length=1)
    organization_code: str = Field(min_length=1)
    status: Literal["REVIEWED", "PUBLISHED", "OBSERVED", "SNAPSHOT"]
    occurrence_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])

    @model_validator(mode="after")
    def status_matches_type(self) -> Evidence:
        expected = {
            "scrap_review": "REVIEWED",
            "report": "PUBLISHED",
            "occurrence": "OBSERVED",
            "metric": "SNAPSHOT",
        }[self.source_type]
        if self.status != expected:
            raise ValueError("source status does not match source type")  # noqa: TRY003
        return self


class AccessScope(Frozen):
    organization_code: str = Field(min_length=1)
    allowed_source_ids: frozenset[str] = Field(default_factory=frozenset[str])
    access_revision: str = Field(min_length=1)


class MetricValue(Frozen):
    key: str = Field(min_length=1)
    value: Decimal
    unit: Literal["BRL", "USD", "count", "units", "percent"]
    source_id: str = Field(min_length=1)


class PeriodScope(Frozen):
    period_from: date
    period_to: date
    cutoff_at: datetime | None = None
    timezone: str = "America/Manaus"
    metric_code: Literal["MATERIAL_SCRAP_COST"] = "MATERIAL_SCRAP_COST"
    metric_policy_version: Literal["scrap-cost-v1"] = "scrap-cost-v1"
    currency: Literal["BRL", "USD"]
    comparison_mode: Literal["NONE", "PREVIOUS_YEAR", "CUSTOM"] = "NONE"
    comparison_from: date | None = None
    comparison_to: date | None = None
    is_provisional: bool = False
    filters: dict[str, Any] = Field(default_factory=dict[str, Any])
    coverage_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def valid_range(self) -> PeriodScope:
        if self.period_to < self.period_from:
            raise ValueError("period_to must be on or after period_from")  # noqa: TRY003
        if self.comparison_mode == "CUSTOM":
            if self.comparison_from is None or self.comparison_to is None:
                raise ValueError("CUSTOM requires comparison dates")  # noqa: TRY003
            if self.comparison_to < self.comparison_from:
                raise ValueError("comparison_to must be on or after comparison_from")  # noqa: TRY003
        elif self.comparison_from is not None or self.comparison_to is not None:
            raise ValueError("comparison dates require CUSTOM mode")  # noqa: TRY003
        return self


class BaseRequest(Frozen):
    contract_version: Literal["1"] = "1"
    request_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    snapshot_id: str = Field(min_length=1)
    access: AccessScope
    sources: tuple[Evidence, ...]

    @model_validator(mode="after")
    def sources_in_scope(self) -> BaseRequest:
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source IDs must be unique within a snapshot")  # noqa: TRY003
        if any(
            source.organization_code != self.access.organization_code
            or source.source_id not in self.access.allowed_source_ids
            for source in self.sources
        ):
            raise ValueError("snapshot includes a source outside the access scope")  # noqa: TRY003
        return self


class ReviewRequest(BaseRequest):
    occurrence_id: str = Field(min_length=1)
    occurrence: dict[str, Any]
    current_review: dict[str, Any] | None = None


class ReportRequest(BaseRequest):
    report_id: str = Field(min_length=1)
    report_kind: ReportKind
    title: str = ""
    description: str = ""
    selected_occurrence_ids: tuple[str, ...]
    metrics: tuple[MetricValue, ...] = ()
    scope: PeriodScope | None = None
    content_schema_version: int = 1

    @model_validator(mode="after")
    def kind_has_valid_scope(self) -> ReportRequest:
        if self.report_kind == "DOSSIER" and self.scope is not None:
            raise ValueError("DOSSIER cannot have a period scope")  # noqa: TRY003
        if self.report_kind == "PERIOD_CLOSE" and (
            self.scope is None or self.content_schema_version < _MIN_PERIOD_CLOSE_SCHEMA
        ):
            raise ValueError("PERIOD_CLOSE requires V2 period scope")  # noqa: TRY003
        source_ids = {source.source_id for source in self.sources if source.source_type == "metric"}
        if any(metric.source_id not in source_ids for metric in self.metrics):
            raise ValueError("metric must cite an authorized snapshot source")  # noqa: TRY003
        if len({metric.key for metric in self.metrics}) != len(self.metrics):
            raise ValueError("metric keys must be unique")  # noqa: TRY003
        if self.scope is not None and any(
            metric.unit in {"BRL", "USD"} and metric.unit != self.scope.currency
            for metric in self.metrics
        ):
            raise ValueError("metric currency does not match report scope")  # noqa: TRY003
        return self


class SupportedStatement(Frozen):
    statement: str = Field(min_length=5, max_length=400)
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=3, max_length=500)


class FourMItem(Frozen):
    family: FourM
    observation: str = ""
    hypothesis: str = ""
    certainty: Literal["UNASSESSED", "HYPOTHESIS", "CONFIRMED"] = "UNASSESSED"
    source_ids: tuple[str, ...] = ()
    next_check: str = ""


class DraftSuggestion(Frozen):
    field: str
    text: str
    source_ids: tuple[str, ...] = ()


class AssistantDraft(Frozen):
    contract_version: Literal["1"] = "1"
    request_id: str
    subject_id: str
    expected_version: int
    snapshot_fingerprint: str
    processing_state: Literal["READY"] = "READY"
    outcome: Literal["COMPLETE", "INSUFFICIENT_EVIDENCE"]
    requires_human_review: Literal[True] = True
    suggestions: tuple[DraftSuggestion, ...] = ()
    claims: tuple[SupportedStatement, ...] = ()
    four_m: tuple[FourMItem, ...] = ()
    gaps: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    run_metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
