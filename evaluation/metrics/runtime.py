"""Latency, generation throughput, and process resource measurements."""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

from evaluation.metrics.stats import percentile

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class LatencySummary:
    mean_seconds: float
    p95_seconds: float
    count: int


@dataclass(slots=True)
class ResourcePeaks:
    ram_gb: float = 0.0
    vram_gb: float = 0.0


def latency_summary(values: Sequence[float]) -> LatencySummary:
    """Summarize per-case latency in seconds."""
    return LatencySummary(fmean(values) if values else 0.0, percentile(values, 0.95), len(values))


def tokens_per_second(completion_tokens: int, generation_seconds: float) -> float:
    """Calculate completion throughput, using zero for unavailable duration."""
    if completion_tokens < 0 or generation_seconds < 0:
        raise ValueError("token count and duration must be non-negative")  # noqa: TRY003
    return completion_tokens / generation_seconds if generation_seconds else 0.0


class ResourceSampler:
    """Sample Python/Ollama RAM and NVIDIA VRAM while the context is active."""

    def __init__(self, interval_seconds: float = 0.2) -> None:
        if interval_seconds <= 0:
            raise ValueError("sampling interval must be positive")  # noqa: TRY003
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample_until_stopped, daemon=True)
        self.peaks = ResourcePeaks()

    def __enter__(self) -> ResourceSampler:
        self._sample_once()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _sample_until_stopped(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self._interval_seconds)

    def _sample_once(self) -> None:
        self.peaks.ram_gb = max(self.peaks.ram_gb, _current_ram_gb())
        self.peaks.vram_gb = max(self.peaks.vram_gb, _current_vram_gb())


def _current_ram_gb() -> float:
    try:
        import psutil  # noqa: PLC0415 - evaluation extra is optional outside this module
    except ImportError:
        return 0.0
    total_bytes = 0
    for process in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (process.info["name"] or "").lower()
            memory = process.info["memory_info"]
        except (psutil.Error, AttributeError):
            continue
        if name.startswith(("python", "ollama")) and memory:
            total_bytes += memory.rss
    return total_bytes / 1024**3


def _current_vram_gb() -> float:
    try:
        executable = shutil.which("nvidia-smi")
        if executable is None:
            return 0.0
        output = subprocess.run(  # noqa: S603 - resolved executable, fixed argument vector
            [executable, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        ).stdout
        return float(output.strip().splitlines()[0]) / 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0.0
