"""Ollama embedding adapter with validated dimensions and bounded batches."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import ollama

from rag_kit.domain.errors import RetrievalError

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class EmbeddingOptions:
    host: str
    model: str
    dimensions: int = 1024
    batch_size: int = 32
    timeout_s: float = 120.0
    keep_alive: str = "10m"


class OllamaEmbedder:
    def __init__(self, options: EmbeddingOptions) -> None:
        if options.batch_size < 1:
            raise ValueError("embedding batch_size must be positive")  # noqa: TRY003 - contextual domain error
        self._options = options
        arguments: dict[str, Any] = {"host": options.host, "timeout": options.timeout_s}
        if "keep_alive" in inspect.signature(ollama.AsyncClient).parameters:
            arguments["keep_alive"] = options.keep_alive
        self._client = ollama.AsyncClient(**arguments)

    @property
    def model_id(self) -> str:
        return self._options.model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._options.batch_size):
            batch = list(texts[offset : offset + self._options.batch_size])
            try:
                response = await self._client.embed(
                    model=self.model_id, input=batch, truncate=False
                )
            except (ollama.ResponseError, httpx.HTTPError) as error:
                raise RetrievalError("local embedding request failed") from error  # noqa: TRY003 - contextual domain error
            if len(response.embeddings) != len(batch) or any(
                len(vector) != self._options.dimensions for vector in response.embeddings
            ):
                raise RetrievalError("embedding count or dimensions differ from configuration")  # noqa: TRY003 - contextual domain error
            vectors.extend(list(vector) for vector in response.embeddings)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def aclose(self) -> None:
        await self._client.close()
