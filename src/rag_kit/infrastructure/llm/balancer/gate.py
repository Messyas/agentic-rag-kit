"""Priority-aware local admission gate with cancellation-safe permits."""

from __future__ import annotations

import asyncio
import heapq
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class PriorityGate:
    def __init__(self, capacity: int = 1) -> None:
        if capacity < 1:
            raise ValueError("gate capacity must be positive")  # noqa: TRY003 - contextual domain error
        self._capacity = capacity
        self._busy = 0
        self._sequence = 0
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []

    async def acquire(self, priority: str = "normal") -> None:
        if self._busy < self._capacity:
            self._busy += 1
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sequence += 1
        heapq.heappush(
            self._waiters,
            ({"high": 0, "normal": 1, "low": 2}.get(priority, 1), self._sequence, future),
        )
        try:
            await future
        except BaseException:
            if future.done() and not future.cancelled():
                self.release()
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                future.set_result(None)
                return
        self._busy = max(0, self._busy - 1)

    @asynccontextmanager
    async def slot(self, priority: str = "normal") -> AsyncGenerator[None]:
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()
