"""Immutable value objects shared across application layers."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    """Base class for immutable domain values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceRef(Frozen):
    source_type: str
    source_id: str
    version: str = "1"

    @property
    def key(self) -> str:
        return f"{self.source_type}:{self.source_id}@{self.version}"


class Document(Frozen):
    ref: SourceRef
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(Frozen):
    chunk_id: str
    ref: SourceRef
    index: int
    content: str
    context_prefix: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def embedding_text(self) -> str:
        return f"{self.context_prefix}\n{self.content}" if self.context_prefix else self.content


class ScoredChunk(Frozen):
    chunk: Chunk
    score: float
    retriever: str
    signals: dict[str, float] = Field(default_factory=dict)


class MetadataFilter(Frozen):
    field: str
    op: Literal["eq", "in", "gte", "lte"] = "eq"
    value: Any


class RetrievalQuery(Frozen):
    text: str
    k: int = 8
    filters: tuple[MetadataFilter, ...] = ()
    source_types: tuple[str, ...] = ()
    purpose: str = "analysis"


class RawTable(Frozen):
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    source_name: str
    warnings: tuple[str, ...] = ()


def make_chunk_id(ref: SourceRef, index: int, content: str) -> str:
    """Build a stable identifier for a source chunk."""
    raw = f"{ref.key}|{index}|{content}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]
