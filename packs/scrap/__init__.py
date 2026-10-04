"""Scrap domain pack and host-record adapters."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from packs.scrap.loaders import GerpTsvLoader
from packs.scrap.query_builder import ScrapQueryBuilder
from packs.scrap.schemas import build_pre_analysis_model, deterministic_facts, load_defect_types
from packs.scrap.tools import FindSimilarReviews, GetReportSources, GetScrapSummary

from rag_kit.application.generation.output_guard import DomainGuard
from rag_kit.application.ingestion.schema_map import ColumnSpec
from rag_kit.application.pack import PackDeps, PackSpec
from rag_kit.domain.analysis import Subject
from rag_kit.domain.errors import ConfigurationError
from rag_kit.domain.models import Document, SourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rag_kit.domain.ports.tool import Tool

_FIELD_MAP = {
    "date": "transaction_date",
    "factory": "organization_code",
    "line": "receipt_department",
    "component": "item_type",
    "component_family": "item_type",
    "quantity": "issue_quantity",
    "cost": "issue_amount_brl",
    "erp_comment": "requisition_comment",
    "original_description": "item_description",
}


def subject_from_record(record: Mapping[str, Any]) -> Subject:
    occurrence_id = record.get("occurrence_id")
    if not occurrence_id:
        raise ConfigurationError("Canonical host records must supply a stable occurrence_id")  # noqa: TRY003 - contextual domain error
    fields = dict(record)
    for target, source in _FIELD_MAP.items():
        if target not in fields and source in record:
            fields[target] = record[source]
    return Subject(
        subject_id=str(occurrence_id),
        kind="scrap_occurrence",
        fields=fields,
        version=str(record.get("content_hash") or record.get("version") or "1"),
    )


def record_to_document(record: Mapping[str, Any]) -> Document:
    source_id = record.get("review_id") or record.get("id")
    if not source_id or record.get("status") != "REVIEWED":
        raise ConfigurationError("Corpus entries require a review ID and REVIEWED status")  # noqa: TRY003 - contextual domain error
    text = "\n".join(
        str(record[name])
        for name in ("title", "description", "cause_description")
        if record.get(name)
    )
    if not text:
        raise ConfigurationError("Reviewed documents must contain analytical text")  # noqa: TRY003 - contextual domain error
    metadata = dict(record.get("metadata") or {})
    for target, source in _FIELD_MAP.items():
        if record.get(target) is not None or record.get(source) is not None:
            metadata[target] = record.get(target, record.get(source))
    for name in ("period", "product", "report_id"):
        if record.get(name) is not None:
            metadata[name] = record[name]
    metadata["occurrence_id"] = str(record.get("occurrence_id", ""))
    return Document(
        ref=SourceRef(
            source_type="scrap_review",
            source_id=str(source_id),
            version=str(record.get("version", "1")),
        ),
        text=text,
        metadata=metadata,
    )


def trusted_numbers(subject: Subject) -> Mapping[str, str]:
    return {
        name: str(Decimal(str(subject.fields[name])))
        for name in ("quantity", "cost", "issue_amount_brl", "amount_usd", "issue_quantity")
        if subject.fields.get(name) is not None
    }


def _tools(deps: PackDeps) -> Sequence[Tool]:
    tools: list[Tool] = [FindSimilarReviews(deps.retriever), GetReportSources(deps.retriever)]
    metrics = deps.extras.get("metrics")
    if metrics is not None:
        tools.insert(0, GetScrapSummary(metrics))
    return tools


def build_pack(defect_types_path: Path | None = None) -> PackSpec:
    directory = Path(__file__).parent
    config = yaml.safe_load((directory / "column_map.yaml").read_text(encoding="utf-8"))
    specs = tuple(
        ColumnSpec(
            canonical_name=column["name"],
            aliases=tuple(column.get("aliases", [])),
            required=column.get("required", False),
            dtype=column.get("dtype", "str"),
        )
        for column in config["columns"]
    )
    return PackSpec(
        name="scrap",
        output_model=build_pre_analysis_model(defect_types_path),
        prompts_dir=directory / "prompts",
        column_specs=specs,
        record_to_document=record_to_document,
        subject_from_record=subject_from_record,
        query_builder=ScrapQueryBuilder(),
        deterministic_facts=deterministic_facts,
        trusted_numbers=trusted_numbers,
        build_tools=_tools,
        loaders={suffix: GerpTsvLoader() for suffix in ("", ".tsv", ".txt")},
        guards=lambda: (DomainGuard(load_defect_types(defect_types_path)),),
    )
