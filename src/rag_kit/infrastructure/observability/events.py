"""Container-scoped observers with ordered delivery and isolated failures."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Any], Awaitable[None] | None]] = []
        self._logger = structlog.get_logger(__name__)

    def subscribe(self, subscriber: Callable[[Any], Awaitable[None] | None]) -> None:
        self._subscribers.append(subscriber)

    async def publish(self, event: Any) -> None:
        for subscriber in tuple(self._subscribers):
            try:
                result = subscriber(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                self._logger.warning(
                    "event_subscriber_failed",
                    error_type=type(error).__name__,
                    event_type=type(event).__name__,
                )


class NullEventBus:
    async def publish(self, event: Any) -> None:  # noqa: ARG002 - event port contract
        return None
