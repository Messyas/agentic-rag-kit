"""Periodic endpoint health probe for the configured local inference pool."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
from contextlib import suppress

import httpx


async def check_health(url: str, provider: str = "ollama") -> bool:
    suffix = "api/tags" if provider == "ollama" else "v1/models"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(url.rstrip("/") + "/" + suffix)
            response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


class BackendHealthMonitor:
    def __init__(
        self,
        urls: dict[str, str],
        update: Callable[[str, bool], None],
        provider: str,
        interval_seconds: float = 10.0,
    ) -> None:
        self._urls = urls
        self._update = update
        self._provider = provider
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        if not urls or interval_seconds <= 0:
            raise ValueError("health monitor needs backends and a positive interval")  # noqa: TRY003

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="rag-kit-backend-health")

    async def _run(self) -> None:
        while True:
            for name, url in self._urls.items():
                healthy = await check_health(url, self._provider)
                self._update(name, healthy)
            await asyncio.sleep(self._interval)

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
