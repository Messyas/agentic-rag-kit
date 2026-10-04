"""Recall-oriented retrieval quality metrics against required source IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    recall_at_k: float
    mean_reciprocal_rank: float
    hit_at_k: float
    case_count: int


def retrieval_metrics(
    ranked_source_ids: Sequence[Sequence[str]],
    required_source_ids: Sequence[Sequence[str]],
    k: int,
) -> RetrievalMetrics:
    """Measure whether each case's required sources appear among ranked results."""
    if len(ranked_source_ids) != len(required_source_ids):
        raise ValueError("ranked and required source case counts differ")  # noqa: TRY003
    if k < 1:
        raise ValueError("k must be positive")  # noqa: TRY003
    if not ranked_source_ids:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0)
    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    hits: list[float] = []
    for ranked, required_values in zip(ranked_source_ids, required_source_ids, strict=True):
        required = set(required_values)
        if not required:
            recall_values.append(0.0)
            reciprocal_ranks.append(0.0)
            hits.append(0.0)
            continue
        top_results = list(ranked[:k])
        found = required.intersection(top_results)
        recall_values.append(len(found) / len(required))
        hits.append(float(bool(found)))
        first_match = next(
            (index for index, item in enumerate(ranked, start=1) if item in required), 0
        )
        reciprocal_ranks.append(1 / first_match if first_match and first_match <= k else 0.0)
    case_count = len(ranked_source_ids)
    return RetrievalMetrics(
        sum(recall_values) / case_count,
        sum(reciprocal_ranks) / case_count,
        sum(hits) / case_count,
        case_count,
    )
