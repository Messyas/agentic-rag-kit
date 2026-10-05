"""Comparable local evaluation for automatic scrap drafts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

import psutil
from packs.scrap.assistant import ScrapAssistantFacade
from packs.scrap.assistant_schemas import AssistantDraft, ReportRequest, ReviewRequest
from packs.scrap.local_batch import build_local_requests, reviewed_evidence
from pydantic import Field

from rag_kit.application.ingestion.pipeline import prepare_table
from rag_kit.bootstrap.container import Container
from rag_kit.domain.models import Frozen
from rag_kit.domain.ports.llm import LLMRequest, LLMResponse

if TYPE_CHECKING:
    from pathlib import Path

    from rag_kit.bootstrap.settings import Settings


class DraftEvalCase(Frozen):
    case_id: str
    split: Literal["dev", "test"]
    row_index: int = Field(ge=0)
    kind: Literal["review", "report"]
    expected_families: tuple[Literal["MAN", "MACHINE", "METHOD", "MATERIAL"], ...]


class _NoModel:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"context": [], "hypotheses": [], "gaps": []}), model=request.model
        )

    async def aclose(self) -> None:
        return


@dataclass(frozen=True, slots=True)
class DraftEvalOptions:
    cases_path: Path
    source_path: Path
    reviews_path: Path
    output_dir: Path
    split: Literal["dev", "test"] = "test"
    repetitions: int = 1


def load_cases(path: Path) -> tuple[DraftEvalCase, ...]:
    rows = [
        DraftEvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [case.case_id for case in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate draft evaluation case ID")  # noqa: TRY003
    keys = [(case.row_index, case.kind) for case in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source row and kind in evaluation")  # noqa: TRY003
    return tuple(rows)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    position = min(len(sorted_values) - 1, int(fraction * (len(sorted_values) - 1) + 0.5))
    return sorted_values[position]


async def measure_draft(  # noqa: C901, PLR0915 - process sampling wraps a draft call
    assistant: ScrapAssistantFacade,
    request: ReviewRequest | ReportRequest,
    *,
    model_process_names: frozenset[str] = frozenset(),
) -> tuple[AssistantDraft, float, int]:
    process = psutil.Process()

    def rss_bytes() -> int:
        total = process.memory_info().rss
        if model_process_names:
            for candidate in psutil.process_iter(["name"]):
                try:
                    if (candidate.info["name"] or "").casefold() in model_process_names:
                        total += candidate.memory_info().rss
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        return total

    peak = rss_bytes()
    active = True

    async def sample() -> None:
        nonlocal peak
        while active:
            peak = max(peak, rss_bytes())
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(sample())
    started = perf_counter()
    try:
        if isinstance(request, ReviewRequest):
            draft = await assistant.suggest_review(request)
        else:
            draft = await assistant.draft_report(request)
    finally:
        active = False
        await watcher
        peak = max(peak, rss_bytes())
    return draft, perf_counter() - started, peak


def _score(draft: AssistantDraft, expected: set[str]) -> dict[str, Any]:
    detected = {item.family for item in draft.four_m if item.hypothesis}
    known = set(draft.source_refs)
    citation_valid = all(
        any(
            ref.startswith(f"{kind}:{claim.source_id}@")
            for ref in known
            for kind in ("occurrence", "scrap_review", "report", "metric")
        )
        for claim in draft.claims
    )
    return {
        "family_exact": detected == expected,
        "detected_families": sorted(detected),
        "expected_families": sorted(expected),
        "citation_valid": citation_valid,
        "schema_valid": True,
        "outcome": draft.outcome,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [row for row in rows if row.get("error") is None]
    seconds = [float(row["latency_s"]) for row in successes]
    return {
        "cases": len(rows),
        "failures": len(rows) - len(successes),
        "family_exact": sum(bool(row.get("family_exact")) for row in successes),
        "citation_valid": sum(bool(row.get("citation_valid")) for row in successes),
        "schema_valid": len(successes),
        "mean_latency_s": statistics.mean(seconds) if seconds else None,
        "p95_latency_s": _percentile(seconds, 0.95) if seconds else None,
        "peak_process_ram_gb": max((row.get("peak_ram_bytes", 0) for row in successes), default=0)
        / 1_000_000_000,
    }


async def evaluate_drafts(  # noqa: PLR0915 - evaluation captures all arms and artifacts
    settings: Settings, options: DraftEvalOptions
) -> dict[str, Any]:
    cases = [case for case in load_cases(options.cases_path) if case.split == options.split]
    if options.repetitions < 1:
        raise ValueError("repetitions must be positive")  # noqa: TRY003
    options.output_dir.mkdir(parents=True, exist_ok=True)
    review_rows = [
        json.loads(line)
        for line in options.reviews_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    async with Container(settings) as container:
        table = container.load_table(options.source_path)
        prepared = prepare_table(table, container.pack.column_specs)
        pairs = build_local_requests(
            prepared.rows, options.source_path.name, reviewed=reviewed_evidence(review_rows)
        )
        if any(case.row_index >= len(pairs) for case in cases):
            raise ValueError("evaluation row index outside accepted source rows")  # noqa: TRY003
        arms = {
            "rule_baseline": ScrapAssistantFacade(_NoModel(), settings.ollama.llm_model),
            "local_rag": container.build_scrap_assistant(),
        }
        summaries: dict[str, Any] = {}
        for arm_name, assistant in arms.items():
            results: list[dict[str, Any]] = []
            for repetition in range(options.repetitions):
                for case in cases:
                    pair = pairs[case.row_index]
                    request = pair[0] if case.kind == "review" else pair[1]
                    try:
                        model_process_names: frozenset[str] = (
                            frozenset[str]({"ollama", "ollama.exe"})
                            if arm_name == "local_rag"
                            else frozenset()
                        )
                        draft, duration, peak = await measure_draft(
                            assistant, request, model_process_names=model_process_names
                        )
                        score = _score(draft, set(case.expected_families))
                        row = {
                            "case_id": case.case_id,
                            "repetition": repetition,
                            "latency_s": duration,
                            "peak_ram_bytes": peak,
                            "error": None,
                            **score,
                        }
                    except Exception as error:
                        row = {
                            "case_id": case.case_id,
                            "repetition": repetition,
                            "error": type(error).__name__,
                        }
                    results.append(row)
            artifact = options.output_dir / f"{arm_name}.jsonl"
            artifact.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
                encoding="utf-8",
            )
            summaries[arm_name] = _summary(results)
        manifest = {
            "split": options.split,
            "repetitions": options.repetitions,
            "cases_sha256": hashlib.sha256(options.cases_path.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(options.source_path.read_bytes()).hexdigest(),
            "reviews_sha256": hashlib.sha256(options.reviews_path.read_bytes()).hexdigest(),
            "model": settings.ollama.llm_model,
            "arms": summaries,
            "note": "Small synthetic cases; these results do not establish production quality.",
        }
        (options.output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest
