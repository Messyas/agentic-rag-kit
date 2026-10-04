"""Bounded deterministic embedding cache keyed by model and normalized text."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rag_kit.domain.ports.embedder import Embedder


class CachingEmbedder:
    def __init__(self, inner: Embedder, capacity: int = 10000) -> None:
        if capacity < 1:
            raise ValueError("embedding cache capacity must be positive")  # noqa: TRY003
        self._inner = inner
        self._capacity = capacity
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def _key(self, text: str) -> str:
        return hashlib.sha256((self.model_id + "\0" + text).encode()).hexdigest()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        keys = [self._key(text) for text in texts]
        missing: dict[str, str] = {}
        for key, content in zip(keys, texts, strict=True):
            if key not in self._cache:
                missing.setdefault(key, content)
        if missing:
            vectors = await self._inner.embed_documents(tuple(missing.values()))
            if len(vectors) != len(missing):
                raise ValueError("embedder returned a mismatched batch")  # noqa: TRY003
            for key, vector in zip(missing, vectors, strict=True):
                self._cache[key] = tuple(vector)
                self._cache.move_to_end(key)
        result = [list(self._cache[key]) for key in keys]
        for key in keys:
            self._cache.move_to_end(key)
        while len(self._cache) > self._capacity:
            self._cache.popitem(last=False)
        return result

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents((text,)))[0]

    async def aclose(self) -> None:
        await self._inner.aclose()
