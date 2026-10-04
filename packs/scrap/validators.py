"""Scrap output guards for source-backed claims and controlled defect types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from packs.scrap.schemas import PreAnalysis, load_defect_types

from rag_kit.domain.errors import GuardrailError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pydantic import BaseModel


class ScrapOutputGuard:
    """Reject invalid defect labels and unsupported source references."""

    def validate(self, output: BaseModel, trusted_source_ids: Iterable[str]) -> None:
        if not isinstance(output, PreAnalysis):
            raise GuardrailError("scrap output must use the PreAnalysis schema")  # noqa: TRY003
        allowed = set(load_defect_types())
        record = output.proposed_record
        if record and record.defect_type and record.defect_type not in allowed:
            raise GuardrailError("proposed defect type is outside the controlled vocabulary")  # noqa: TRY003
        trusted = set(trusted_source_ids)
        cited = {source_id for claim in output.claims() for source_id in claim.source_ids}
        unknown = cited - trusted
        if unknown:
            raise GuardrailError(f"scrap output cites unknown source IDs: {sorted(unknown)}")  # noqa: TRY003


def validate_defect_type(value: str | None) -> bool:
    """Check a proposed defect label against the pack's controlled vocabulary."""
    return value is None or value in set(load_defect_types())
