"""Optional CPU sentence-transformers embedding adapter."""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


class SentenceTransformerEmbedder:
    def __init__(self, model: str, device: str = "cpu") -> None:
        self._model_id = model
        module = import_module("sentence_transformers")
        self._model: Any = module.SentenceTransformer(model, device=device)

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: Any = await asyncio.to_thread(
            self._model.encode, list(texts), normalize_embeddings=True
        )
        return vectors.tolist()

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def aclose(self) -> None:
        return None
