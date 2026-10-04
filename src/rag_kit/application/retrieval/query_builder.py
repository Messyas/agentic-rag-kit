"""Domain-independent fallback query builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_kit.domain.models import RetrievalQuery

if TYPE_CHECKING:
    from rag_kit.domain.analysis import Subject


class FieldQueryBuilder:
    def __init__(self, fields: tuple[str, ...]) -> None:
        self._fields = fields

    def build(self, subject: Subject) -> RetrievalQuery:
        return RetrievalQuery(
            text=" ".join(
                str(subject.fields[name]) for name in self._fields if subject.fields.get(name)
            )
        )
