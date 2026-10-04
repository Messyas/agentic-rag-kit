"""Tracing protocol and no-op implementation."""

from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol, cast, runtime_checkable


class Span(Protocol):
    def set(self, key: str, value: Any) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def span(self, name: str, **attributes: Any) -> AbstractContextManager[Span]: ...


class _NullSpan:
    def set(self, key: str, value: Any) -> None:  # noqa: ARG002
        return None


class NullTracer:
    @contextmanager
    def span(self, name: str, **attributes: Any) -> Generator[Span]:  # noqa: ARG002 - port signature retained
        yield cast("Span", _NullSpan())
