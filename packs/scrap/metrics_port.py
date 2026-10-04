"""Host-provided read-only scrap metrics port."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence


class MetricsSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_cost: Decimal
    total_qty: Decimal
    n_occurrences: int
    currency: str
    period: str
    coverage: float
    unknown: Mapping[str, int] = {}


class MetricsTrend(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    period: str
    total_cost: Decimal
    total_qty: Decimal
    n_occurrences: int


class ScrapMetricsPort(Protocol):
    """Read-only aggregate access implemented by the host application."""

    async def summary(self, filters: Mapping[str, Any]) -> MetricsSummary: ...

    async def trend(self, filters: Mapping[str, Any], period: str) -> Sequence[MetricsTrend]: ...

    async def top_drivers(
        self, filters: Mapping[str, Any], limit: int
    ) -> Sequence[Mapping[str, Any]]: ...
