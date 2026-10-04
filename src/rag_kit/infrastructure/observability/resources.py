"""Current process memory snapshot without evaluation dependencies."""

from dataclasses import dataclass

import psutil


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    ram_gb: float


def snapshot() -> ResourceSnapshot:

    return ResourceSnapshot(psutil.Process().memory_info().rss / 1024**3)
