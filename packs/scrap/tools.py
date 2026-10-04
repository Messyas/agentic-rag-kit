"""Read-only typed tools exposed by the scrap investigation agent."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from rag_kit.domain.models import MetadataFilter, RetrievalQuery
from rag_kit.domain.ports.llm import ToolSpec
from rag_kit.domain.ports.tool import ToolResult

if TYPE_CHECKING:
    from packs.scrap.metrics_port import ScrapMetricsPort

    from rag_kit.domain.ports.retriever import Retriever


class SummaryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(min_length=1, max_length=32)
    factory: str | None = None
    line: str | None = None


class SimilarReviewsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=5)
    factory: str | None = None


class ReportSourcesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(min_length=1, max_length=200)


class GetScrapSummary:
    def __init__(self, metrics: ScrapMetricsPort) -> None:
        self._metrics = metrics

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "get_scrap_summary",
            "Return deterministic scrap aggregates with coverage.",
            self.args_model,
        )

    @property
    def args_model(self) -> type[BaseModel]:
        return SummaryArguments

    async def run(self, arguments: BaseModel) -> ToolResult:
        args = SummaryArguments.model_validate(arguments)
        filters = {
            key: value
            for key, value in {
                "period": args.period,
                "factory": args.factory,
                "line": args.line,
            }.items()
            if value is not None
        }
        summary = await self._metrics.summary(filters)
        data = summary.model_dump(mode="json")
        identity = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:16]
        source_id = "scrap_metrics:" + identity
        data["sources"] = [{"source_id": source_id, "text": json.dumps(data, ensure_ascii=False)}]
        return ToolResult(
            content=json.dumps(data, ensure_ascii=False),
            data=data,
            source_ids=(source_id,),
            trusted_numbers={
                f"{source_id}:{label}": str(getattr(summary, label))
                for label in ("total_cost", "total_qty", "n_occurrences")
            },
        )


class FindSimilarReviews:
    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "find_similar_reviews",
            "Find reviewed scrap occurrences with evidence sources.",
            self.args_model,
        )

    @property
    def args_model(self) -> type[BaseModel]:
        return SimilarReviewsArguments

    async def run(self, arguments: BaseModel) -> ToolResult:
        args = SimilarReviewsArguments.model_validate(arguments)
        filters = (MetadataFilter(field="factory", value=args.factory),) if args.factory else ()
        matches = await self._retriever.retrieve(
            RetrievalQuery(
                text=args.text, k=args.k, filters=filters, source_types=("scrap_review",)
            )
        )
        records = [
            {"source_id": item.chunk.ref.source_id, "text": item.chunk.content, "score": item.score}
            for item in matches[: args.k]
        ]
        return ToolResult(
            content=json.dumps(
                {"results": records, "sources": [item["source_id"] for item in records]},
                ensure_ascii=False,
            ),
            data={"results": records},
            source_ids=tuple(str(item["source_id"]) for item in records),
        )


class GetReportSources:
    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "get_report_sources", "Retrieve source excerpts belonging to a report.", self.args_model
        )

    @property
    def args_model(self) -> type[BaseModel]:
        return ReportSourcesArguments

    async def run(self, arguments: BaseModel) -> ToolResult:
        args = ReportSourcesArguments.model_validate(arguments)
        matches = await self._retriever.retrieve(
            RetrievalQuery(
                text=args.report_id,
                k=5,
                filters=(MetadataFilter(field="report_id", value=args.report_id),),
                source_types=("report",),
            )
        )
        records = [
            {"source_id": item.chunk.ref.source_id, "text": item.chunk.content} for item in matches
        ]
        return ToolResult(
            content=json.dumps({"sources": records}, ensure_ascii=False),
            data={"sources": records},
            source_ids=tuple(str(item["source_id"]) for item in records),
        )


def build_tools(
    metrics: ScrapMetricsPort, retriever: Retriever
) -> tuple[GetScrapSummary, FindSimilarReviews, GetReportSources]:
    """Compose the pack's three planned read-only tools."""
    return GetScrapSummary(metrics), FindSimilarReviews(retriever), GetReportSources(retriever)


def _spec(name: str, description: str, model: type[BaseModel]) -> ToolSpec:
    return ToolSpec(name=name, description=description, parameters_schema=model.model_json_schema())
