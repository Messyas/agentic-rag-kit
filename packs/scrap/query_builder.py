"""Build evidence searches from structured scrap occurrence fields."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rag_kit.domain.models import MetadataFilter, RetrievalQuery

if TYPE_CHECKING:
    from rag_kit.domain.analysis import Subject

_GENERIC_COMMENTS = frozenset({"", "0", "00", "000", "na", "n/a", "none", "null", "-"})
_GENERIC_CODE_LENGTH = 5


class ScrapQueryBuilder:
    """Prefer descriptive occurrence fields and omit generic ERP comments."""

    def build(self, subject: Subject) -> RetrievalQuery:
        fields = subject.fields
        query_fields = (
            "component_family",
            "product",
            "process_step",
            "defect_keywords",
        )
        terms = [str(fields[name]).strip() for name in query_fields if fields.get(name)]
        comment = fields.get("erp_comment")
        if comment is not None and not _is_generic_comment(str(comment)):
            terms.append(str(comment).strip())
        filters: list[MetadataFilter] = []
        if fields.get("factory"):
            filters.append(MetadataFilter(field="factory", value=fields["factory"]))
        if fields.get("component_family"):
            filters.append(
                MetadataFilter(field="component_family", value=fields["component_family"])
            )
        return RetrievalQuery(
            text=" ".join(term for term in terms if term),
            filters=tuple(filters),
            source_types=("scrap_review",),
        )


def _is_generic_comment(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.strip().casefold())
    compact = re.sub(r"[\s-]+", "", normalized)
    return (
        normalized in _GENERIC_COMMENTS
        or (len(compact) <= _GENERIC_CODE_LENGTH and compact.isalnum())
        or bool(re.fullmatch(r"scrap\s+\w+|no production|reposi.*de scrap", normalized))
    )
