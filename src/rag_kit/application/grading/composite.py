"""Combine deterministic prefiltering and semantic sufficiency grading."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag_kit.domain.models import ScoredChunk
    from rag_kit.domain.ports.grader import Grader, GradeResult


class CompositeGrader:
    def __init__(self, prefilter: Grader, semantic: Grader) -> None:
        self._prefilter = prefilter
        self._semantic = semantic

    async def grade(self, query: str, candidates: tuple[ScoredChunk, ...]) -> GradeResult:
        first = await self._prefilter.grade(query, candidates)
        selected = tuple(
            item for item in candidates if item.chunk.chunk_id in first.relevant_chunks
        )
        return await self._semantic.grade(query, selected) if selected else first
