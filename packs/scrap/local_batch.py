"""Deterministic local snapshots from accepted manual spreadsheet rows."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from packs.scrap.assistant_schemas import AccessScope, Evidence, ReportRequest, ReviewRequest

if TYPE_CHECKING:
    from collections.abc import Sequence


def _identity(source_name: str, position: int, row: dict[str, Any]) -> str:
    value = json.dumps(
        {"source": source_name, "row": position, "record": row},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def build_local_requests(
    rows: Sequence[dict[str, Any]],
    source_name: str,
    *,
    limit: int | None = None,
    reviewed: Sequence[Evidence] = (),
) -> tuple[tuple[ReviewRequest, ReportRequest], ...]:
    """Create one review and one dossier snapshot per accepted row for a local PoC."""
    pairs: list[tuple[ReviewRequest, ReportRequest]] = []
    selected = rows[:limit] if limit is not None else rows
    for position, row in enumerate(selected, 1):
        organization = str(row.get("organization_code") or "").strip()
        if not organization:
            continue
        identity = _identity(source_name, position, row)
        occurrence_id = f"local:{identity}"
        source_id = f"occurrence:{identity}"
        fields = (
            "transaction_date",
            "item_code",
            "item_description",
            "receipt_department",
            "requisition_reason",
            "requisition_comment",
        )
        text = "\n".join(
            f"{name}: {row[name]}" for name in fields if row.get(name) not in (None, "")
        )
        if not text:
            text = "Ocorrência importada sem descrição analítica."
        source = Evidence(
            source_id=source_id,
            source_type="occurrence",
            version=identity,
            text=text,
            organization_code=organization,
            status="OBSERVED",
            occurrence_id=occurrence_id,
            metadata={"source_name": source_name, "row_position": position},
        )
        related = tuple(
            source
            for source in reviewed
            if source.organization_code == organization and source.source_id != source_id
        )
        sources = (source, *related)
        access = AccessScope(
            organization_code=organization,
            allowed_source_ids=frozenset(item.source_id for item in sources),
            access_revision=f"local:{identity}",
        )
        common: dict[str, Any] = {
            "expected_version": 1,
            "snapshot_id": identity,
            "access": access,
            "sources": sources,
        }
        review = ReviewRequest(
            request_id=f"review:{identity}",
            occurrence_id=occurrence_id,
            occurrence=row,
            **common,
        )
        label = str(row.get("item_description") or row.get("item_code") or "ocorrência")
        report = ReportRequest(
            request_id=f"report:{identity}",
            report_id=f"local-report:{identity}",
            report_kind="DOSSIER",
            title=f"Relatório de scrap - {label[:80]}",
            selected_occurrence_ids=(occurrence_id,),
            **common,
        )
        pairs.append((review, report))
    return tuple(pairs)


def reviewed_evidence(records: Sequence[dict[str, Any]]) -> tuple[Evidence, ...]:
    """Accept only explicit, nonempty human-reviewed records for local retrieval."""
    result: list[Evidence] = []
    for record in records:
        if record.get("status") != "REVIEWED":
            continue
        source_id = record.get("review_id") or record.get("id")
        organization = record.get("organization_code")
        text = "\n".join(
            str(record[name]).strip()
            for name in ("title", "description", "cause_description")
            if record.get(name)
        )
        if not source_id or not organization or not text:
            continue
        result.append(
            Evidence(
                source_id=str(source_id),
                source_type="scrap_review",
                version=str(record.get("version") or "1"),
                text=text,
                organization_code=str(organization),
                status="REVIEWED",
                occurrence_id=str(record["occurrence_id"]) if record.get("occurrence_id") else None,
                metadata={
                    "cause_family": record.get("cause_family"),
                    "cause_certainty": record.get("cause_certainty"),
                },
            )
        )
    return tuple(result)
