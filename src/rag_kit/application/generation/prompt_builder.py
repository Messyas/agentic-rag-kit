"""Bounded source serialization for structured generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

from rag_kit.domain.errors import LLMOutputError
from rag_kit.domain.ports.llm import Message

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rag_kit.application.generation.prompt_registry import PromptRegistry
    from rag_kit.domain.analysis import Subject
    from rag_kit.domain.models import ScoredChunk


class PromptBuilder:
    def __init__(
        self,
        registry: PromptRegistry,
        max_context_tokens: int = 4096,
        output_reserve_tokens: int = 1200,
    ) -> None:
        self._registry = registry
        self._max_context_chars = max(256, (max_context_tokens - output_reserve_tokens) * 3)

    def build(
        self,
        subject: Subject,
        evidence: Sequence[ScoredChunk],
        numbers: Mapping[str, str],
        schema: type[BaseModel] | None = None,
    ) -> list[Message]:
        system = self._registry.render("generator.v1.jinja", {})
        data: dict[str, Any] = {
            "subject": subject.fields,
            "sources": [],
            "trusted_figures": numbers,
        }
        base_chars = len(json.dumps(data, ensure_ascii=False, default=str))
        schema_chars = (
            len(json.dumps(schema.model_json_schema(), ensure_ascii=False)) if schema else 0
        )
        input_budget = self._max_context_chars - len(system) - base_chars - schema_chars
        if input_budget < 0:
            raise LLMOutputError("subject and output schema exceed the configured context budget")  # noqa: TRY003
        sources: list[dict[str, str]] = []
        for item in evidence:
            source_id = item.chunk.ref.source_id
            overhead = len(json.dumps({"source_id": source_id, "text": ""}, ensure_ascii=False)) + 1
            remaining = (
                input_budget
                - sum(len(source["text"]) for source in sources)
                - overhead * (len(sources) + 1)
            )
            text = item.chunk.content[: max(0, remaining)]
            if not text:
                break
            sources.append({"source_id": source_id, "text": text})
        data["sources"] = sources
        return [
            Message(role="system", content=system),
            Message(role="user", content=json.dumps(data, ensure_ascii=False, default=str)),
        ]
