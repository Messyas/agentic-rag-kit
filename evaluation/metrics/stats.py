"""Uncertainty intervals and summary statistics for evaluation results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class RateResult:
    """A measured success rate with its sample size and confidence interval."""

    name: str
    successes: int
    trials: int

    def __post_init__(self) -> None:
        if self.trials < 0 or self.successes < 0 or self.successes > self.trials:
            raise ValueError("rate counts must satisfy 0 <= successes <= trials")  # noqa: TRY003

    @property
    def rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0

    @property
    def wilson_interval(self) -> tuple[float, float]:
        """Return the 95% Wilson score interval for the observed rate."""
        if not self.trials:
            return 0.0, 0.0
        z_value = 1.96
        count = self.trials
        proportion = self.rate
        denominator = 1 + z_value**2 / count
        centre = (proportion + z_value**2 / (2 * count)) / denominator
        half_width = (
            z_value
            * math.sqrt(proportion * (1 - proportion) / count + z_value**2 / (4 * count**2))
            / denominator
        )
        return max(0.0, centre - half_width), min(1.0, centre + half_width)

    def meets_target(self, target: float = 0.99, floor: float = 0.95) -> str:
        """Classify the observed rate against the backlog's target and floor."""
        if self.rate >= target:
            return "meets_target"
        return "above_floor" if self.rate > floor else "below_floor"


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return the nearest-rank percentile (empty input produces zero)."""
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be in [0, 1]")  # noqa: TRY003
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]
