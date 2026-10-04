"""Nested JSONL spans containing metadata and timings only."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from rag_kit.domain.ports.tracer import Span


class JsonlSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        if key not in {"prompt", "response", "content", "subject", "messages"}:
            self.attributes[key] = value


class JsonlTracer:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._parent: ContextVar[str | None] = ContextVar("parent_span", default=None)

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Generator[Span]:
        span = JsonlSpan()
        for key, value in attributes.items():
            span.set(key, value)
        parent = self._parent.get()
        span_id = str(uuid.uuid4())
        token = self._parent.set(span_id)
        started = time.perf_counter()
        error_name: str | None = None
        try:
            yield span
        except BaseException as error:
            error_name = type(error).__name__
            raise
        finally:
            self._parent.reset(token)
            record = {
                "name": name,
                "span_id": span_id,
                "parent_span_id": parent,
                "duration_seconds": time.perf_counter() - started,
                "attributes": span.attributes,
                "error": error_name,
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, default=str) + "\n")
