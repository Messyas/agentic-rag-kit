"""Domain event bus protocol."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: Any) -> None: ...
