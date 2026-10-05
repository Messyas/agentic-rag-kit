"""Pure payload mapping for a future Hanaro adapter; never writes to the host."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packs.scrap.assistant_schemas import AssistantDraft

_NARRATIVE_SECTIONS = {"CONTEXT": "context", "CONCLUSIONS": "conclusions"}


def _fields(draft: AssistantDraft) -> dict[str, str]:
    if draft.outcome != "COMPLETE":
        raise ValueError("insufficient draft cannot be mapped for acceptance")  # noqa: TRY003
    return {suggestion.field: suggestion.text for suggestion in draft.suggestions}


def review_write_payload(draft: AssistantDraft) -> dict[str, Any]:
    """Produce the fields understood by Hanaro's ScrapReviewWrite schema."""
    values = _fields(draft)
    if "description" not in values:
        raise ValueError("review draft has no supported description")  # noqa: TRY003
    payload: dict[str, Any] = {
        "title": values["title"],
        "description": values["description"],
        "expected_version": draft.expected_version,
    }
    if "cause_family" in values and "cause_description" in values:
        payload.update(
            cause_family=values["cause_family"],
            cause_description=values["cause_description"],
            cause_certainty="HYPOTHESIS",
        )
    return payload


def report_update_payload(draft: AssistantDraft) -> dict[str, Any]:
    """Produce a ReportUpdate without changing unrelated human-edited fields."""
    values = _fields(draft)
    payload: dict[str, Any] = {"expected_version": draft.expected_version}
    for key in ("title", "description", "objective", "executive_summary"):
        if key in values:
            payload[key] = values[key]
    return payload


def report_sections_payload(
    draft: AssistantDraft, existing_sections: list[dict[str, Any]], *, expected_version: int
) -> dict[str, Any]:
    """Merge narrative text into the full section list required by ReportSectionsUpdate."""
    values = _fields(draft)
    if expected_version != draft.expected_version:
        raise ValueError("draft version is stale; regenerate before applying")  # noqa: TRY003
    sections: list[dict[str, Any]] = []
    found: set[str] = set()
    for source in existing_sections:
        section = {
            key: source[key]
            for key in (
                "section_key",
                "kind",
                "enabled",
                "title",
                "payload_schema_version",
                "payload",
            )
            if key in source
        }
        for field, section_key in _NARRATIVE_SECTIONS.items():
            if field in values and section.get("section_key") == section_key:
                section["payload"] = {**section.get("payload", {}), "text": values[field]}
                found.add(field)
        sections.append(section)
    required = set(values) & set(_NARRATIVE_SECTIONS)
    if missing := required - found:
        raise ValueError(f"narrative sections missing: {sorted(missing)}")  # noqa: TRY003
    return {"expected_version": expected_version, "sections": sections}
