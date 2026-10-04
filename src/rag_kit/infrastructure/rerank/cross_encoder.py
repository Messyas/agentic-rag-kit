"""Optional sentence-transformers cross-encoder reranking adapter."""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rag_kit.domain.models import ScoredChunk


class CrossEncoderReranker:
    def __init__(self, model: str, device: str = "cpu") -> None:
        module = import_module("sentence_transformers")
        self._model: Any = module.CrossEncoder(model, device=device)

    async def rerank(
        self, query_text: str, candidates: Sequence[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        pairs = [(query_text, item.chunk.content) for item in candidates]
        scores: Any = await asyncio.to_thread(self._model.predict, pairs)
        ranked = [
            item.model_copy(
                update={"score": float(score), "signals": {**item.signals, "rerank": float(score)}}
            )
            for item, score in zip(candidates, scores, strict=True)
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_k]
