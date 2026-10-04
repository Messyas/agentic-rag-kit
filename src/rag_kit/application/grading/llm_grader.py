"""Schema-constrained relevance and sufficiency evaluator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rag_kit.domain.ports.grader import GradeResult
from rag_kit.domain.ports.llm import LLMUsage, Message

if TYPE_CHECKING:
    from rag_kit.application.generation.generator import StructuredOutputRunner
    from rag_kit.application.generation.prompt_registry import PromptRegistry
    from rag_kit.domain.models import ScoredChunk


class LLMGrader:
    def __init__(self, runner: StructuredOutputRunner, prompts: PromptRegistry) -> None:
        self._runner = runner
        self._prompts = prompts
        self.last_usage = LLMUsage()

    async def grade(self, query: str, candidates: tuple[ScoredChunk, ...]) -> GradeResult:
        if not candidates:
            return GradeResult(sufficient=False, rationale="No evidence found.")
        data = {
            "query": query,
            "sources": [
                {"chunk_id": item.chunk.chunk_id, "content": item.chunk.content[:2000]}
                for item in candidates
            ],
        }
        output = await self._runner.run(
            [
                Message(role="system", content=self._prompts.render("grader.v1.jinja", {})),
                Message(role="user", content=json.dumps(data, ensure_ascii=False)),
            ],
            GradeResult,
        )
        result = GradeResult.model_validate(output.value)
        self.last_usage = output.usage
        valid_ids = {item.chunk.chunk_id for item in candidates}
        if any(grade.chunk_id not in valid_ids for grade in result.grades) or (
            result.sufficient and not result.relevant_chunks
        ):
            return GradeResult(sufficient=False, rationale="Evaluator cited unknown chunks.")
        return result
