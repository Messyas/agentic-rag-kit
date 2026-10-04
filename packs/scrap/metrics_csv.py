"""Deterministic snapshot metrics for the local PoC."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from packs.scrap.metrics_port import MetricsSummary, MetricsTrend

from rag_kit.application.ingestion.validators import parse_value

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class CsvMetricsAdapter:
    def __init__(self, records: Sequence[Mapping[str, Any]], currency: str = "BRL") -> None:
        self._records = tuple(dict(record) for record in records)
        if currency not in {"BRL", "USD"}:
            raise ValueError("currency must be BRL or USD")  # noqa: TRY003
        self._currency = currency

    def _selected(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in self._records:
            identity = record.get("occurrence_id")
            if not identity:
                raise ValueError("metrics records require occurrence_id")  # noqa: TRY003 - contextual domain error
            normalized = dict(record)
            normalized.setdefault("factory", record.get("organization_code"))
            normalized.setdefault("line", record.get("receipt_department"))
            if not normalized.get("period") and record.get("transaction_date"):
                normalized["period"] = str(parse_value(record["transaction_date"], "date"))[:7]
            latest[str(identity)] = normalized
        return [
            record
            for record in latest.values()
            if record.get("occurrence_status", "ACTIVE") == "ACTIVE"
            and all(value == "all" or record.get(name) == value for name, value in filters.items())
        ]

    async def summary(self, filters: Mapping[str, Any]) -> MetricsSummary:
        records = self._selected(filters)
        cost_key = "amount_usd" if self._currency == "USD" else "issue_amount_brl"
        counted = [record for record in records if record.get("to_be_counted", True)]
        known_cost = [record for record in counted if record.get(cost_key) is not None]
        known_qty = [record for record in counted if record.get("issue_quantity") is not None]
        return MetricsSummary(
            total_cost=sum((Decimal(str(record[cost_key])) for record in known_cost), Decimal(0)),
            total_qty=sum(
                (Decimal(str(record["issue_quantity"])) for record in known_qty), Decimal(0)
            ),
            n_occurrences=len(records),
            currency=self._currency,
            period=str(filters.get("period", "all")),
            coverage=len(known_cost) / len(records) if records else 0.0,
            unknown={
                "cost": len(records) - len(known_cost),
                "quantity": len(records) - len(known_qty),
            },
        )

    async def trend(self, filters: Mapping[str, Any], period: str) -> Sequence[MetricsTrend]:
        if period != "month":
            raise ValueError("PoC trend supports monthly groups")  # noqa: TRY003 - contextual domain error
        periods = sorted(
            {str(record["period"]) for record in self._selected(filters) if record.get("period")}
        )
        results: list[MetricsTrend] = []
        for value in periods:
            summary = await self.summary({**filters, "period": value})
            results.append(
                MetricsTrend(
                    period=value,
                    total_cost=summary.total_cost,
                    total_qty=summary.total_qty,
                    n_occurrences=summary.n_occurrences,
                )
            )
        return results

    async def top_drivers(
        self, filters: Mapping[str, Any], limit: int
    ) -> Sequence[Mapping[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        cost_key = "amount_usd" if self._currency == "USD" else "issue_amount_brl"
        for record in self._selected(filters):
            if not record.get("to_be_counted", True):
                continue
            label = str(record.get("item_type") or record.get("item_code") or "unknown")
            group = groups.setdefault(
                label,
                {
                    "driver": label,
                    "total_cost": Decimal(0),
                    "total_qty": Decimal(0),
                    "n_occurrences": 0,
                    "currency": self._currency,
                },
            )
            group["total_cost"] += Decimal(str(record.get(cost_key) or 0))
            group["total_qty"] += Decimal(str(record.get("issue_quantity") or 0))
            group["n_occurrences"] += 1
        ranked = sorted(groups.values(), key=lambda group: abs(group["total_cost"]), reverse=True)
        return ranked[: max(0, limit)]
