"""Source-grounded evaluation on the anonymized Hanaro transaction export.

This harness measures ingestion and evidence integrity. Without reviewed cause
labels, it deliberately does not report 4M precision or recall.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any

from packs.scrap.assistant import ScrapAssistantFacade
from packs.scrap.assistant_schemas import AssistantDraft, ReportRequest, ReviewRequest
from packs.scrap.local_batch import build_local_requests

from evaluation.draft_eval import measure_draft
from rag_kit.application.ingestion.pipeline import prepare_table
from rag_kit.bootstrap.container import Container
from rag_kit.domain.ports.llm import LLMRequest, LLMResponse

if TYPE_CHECKING:
    from pathlib import Path

    from rag_kit.bootstrap.settings import Settings


class _NoModel:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"context": [], "hypotheses": [], "gaps": []}),
            model=request.model,
        )

    async def aclose(self) -> None:
        return


def _p95(values: list[float]) -> float:
    return sorted(values)[min(len(values) - 1, int(0.95 * (len(values) - 1) + 0.5))]


@dataclass(frozen=True, slots=True)
class HanaroEvalOptions:
    source_path: Path
    output_dir: Path
    limit: int = 24
    resume: bool = False
    repetitions: int = 3


def _stratum(row: dict[str, Any]) -> tuple[str, bool, bool]:
    amount = row.get("issue_amount_brl")
    return (
        str(row.get("organization_code") or ""),
        amount is not None and float(amount) < 0,
        bool(str(row.get("requisition_comment") or "").strip()),
    )


def _sample_indices(rows: tuple[dict[str, Any], ...], limit: int) -> tuple[int, ...]:
    """Round-robin organization, signed amount, and comment-presence strata."""
    if limit < 1:
        raise ValueError("limit must be positive")  # noqa: TRY003
    strata: dict[tuple[str, bool, bool], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        strata[_stratum(row)].append(index)
    for key, indices in strata.items():
        indices.sort(key=lambda index: hashlib.sha256(f"{key}|{index}".encode()).hexdigest())
    ordered = [strata[key] for key in sorted(strata)]
    return tuple(
        index
        for index in itertools.islice(
            (
                index
                for column in itertools.zip_longest(*ordered)
                for index in column
                if index is not None
            ),
            limit,
        )
    )


def _checks(  # noqa: C901, PLR0912, PLR0915 - multiple independent evidence metrics
    draft: AssistantDraft, request: ReviewRequest | ReportRequest
) -> dict[str, Any]:
    sources = {source.source_id: source for source in request.sources}
    refs = set(draft.source_refs)
    all_claims = [*draft.claims]
    claim_source_ids = [claim.source_id for claim in all_claims]
    literal_quotes = [
        claim.source_id in sources and claim.quote in sources[claim.source_id].text
        for claim in all_claims
    ]
    hypotheses = [item for item in draft.four_m if item.hypothesis]
    hypothesis_refs = [source_id for item in hypotheses for source_id in item.source_ids]
    hypothesis_quotes_valid = all(
        item.observation
        and any(
            item.observation.removeprefix("Caso semelhante: ") in sources[source_id].text
            for source_id in item.source_ids
            if source_id in sources
        )
        for item in hypotheses
    )
    expected_refs = {
        f"{source.source_type}:{source.source_id}@{source.version}" for source in sources.values()
    }
    ref_ids_valid = refs <= expected_refs and all(
        source_id in sources
        and any(ref.startswith(f"{sources[source_id].source_type}:{source_id}@") for ref in refs)
        for source_id in (*claim_source_ids, *hypothesis_refs)
    )
    if isinstance(request, ReportRequest):
        selected = set(request.selected_occurrence_ids)
        scope_valid = all(
            source.source_type == "metric" or source.occurrence_id in selected
            for source in sources.values()
            if f"{source.source_type}:{source.source_id}@{source.version}" in refs
        )
    else:
        scope_valid = all(
            source_id in sources for source_id in (*claim_source_ids, *hypothesis_refs)
        )
    observed_fields = {
        "item_description": "Item registrado",
        "requisition_comment": "Observação de origem",
    }
    expected_fields: Counter[tuple[str, str]] = Counter()
    for source in sources.values():
        if source.source_type != "occurrence":
            continue
        for field, label in observed_fields.items():
            marker = f"{field}: "
            if marker not in source.text:
                continue
            value = source.text.split(marker, 1)[1].splitlines()[0].strip()
            if len(value) >= 5 and value.casefold() != "scrap" and not any(  # noqa: PLR2004
                char.isdigit() for char in value
            ):
                expected_fields[(label, value)] += 1
    predicted_fields: Counter[tuple[str, str]] = Counter()
    for claim in all_claims:
        for label in observed_fields.values():
            prefix = f"{label}: "
            if claim.statement.startswith(prefix):
                predicted_fields[(label, claim.statement[len(prefix) :])] += 1
    correct_fields = sum((expected_fields & predicted_fields).values())
    expected_count = sum(expected_fields.values())
    predicted_count = sum(predicted_fields.values())
    false_positive = predicted_count - correct_fields
    false_negative = expected_count - correct_fields
    field_precision = correct_fields / predicted_count if predicted_count else None
    field_recall = correct_fields / expected_count if expected_count else None
    field_f1 = (
        2 * field_precision * field_recall / (field_precision + field_recall)
        if field_precision is not None
        and field_recall is not None
        and field_precision + field_recall > 0
        else (0.0 if field_precision == 0 and field_recall == 0 else None)
    )
    signature_payload = draft.model_dump(mode="json", exclude={"run_metadata"})
    output_signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    usage: dict[str, Any] = draft.run_metadata.get("usage", {})
    return {
        "schema_valid": True,
        "citation_ids_valid": ref_ids_valid,
        "claim_quotes_literal": all(literal_quotes),
        "hypothesis_observations_literal": hypothesis_quotes_valid,
        "source_scope_valid": scope_valid,
        "no_cause_marked_confirmed": all(item.certainty != "CONFIRMED" for item in draft.four_m),
        "claims": len(all_claims),
        "field_expected": expected_count,
        "field_predicted": predicted_count,
        "field_tp": correct_fields,
        "field_fp": false_positive,
        "field_fn": false_negative,
        "field_accuracy": correct_fields / expected_count if expected_count else None,
        "field_precision": field_precision,
        "field_recall": field_recall,
        "field_f1": field_f1,
        "four_m_hypotheses": len(hypotheses),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "generation_tokens_per_s": usage.get("tokens_per_second"),
        "model_duration_s": float(usage.get("total_duration_s", 0) or 0),
        "output_signature": output_signature,
        "outcome": draft.outcome,
    }


async def evaluate_hanaro_data(  # noqa: C901, PLR0912, PLR0915 - evaluate all arms and persist
    settings: Settings, options: HanaroEvalOptions
) -> dict[str, Any]:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    async with Container(settings) as container:
        raw = container.load_table(options.source_path)
        prepared = prepare_table(raw, container.pack.column_specs)
        pairs = build_local_requests(prepared.rows, options.source_path.name)
        indexes = _sample_indices(prepared.rows, options.limit)
        if options.repetitions < 1:
            raise ValueError("repetitions must be positive")  # noqa: TRY003
        arms = {
            "rule_baseline": ScrapAssistantFacade(_NoModel(), settings.ollama.llm_model),
            "local_rag": container.build_scrap_assistant(),
        }
        case_ids = {
            hashlib.sha256(
                f"{options.source_path.name}|{index}|{kind}|{repetition}".encode()
            ).hexdigest()[:16]
            for index in indexes
            for kind in ("review", "report")
            for repetition in range(options.repetitions)
        }
        results: dict[str, list[dict[str, Any]]] = {}
        for arm_name, assistant in arms.items():
            result_path = options.output_dir / f"{arm_name}.jsonl"
            arm_rows = (
                [
                    json.loads(line)
                    for line in result_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if options.resume and result_path.exists()
                else []
            )
            existing_ids = [row.get("case_id") for row in arm_rows]
            if len(existing_ids) != len(set(existing_ids)) or not set(existing_ids) <= case_ids:
                raise ValueError(f"cannot resume incompatible results for {arm_name}")  # noqa: TRY003
            if result_path.exists() and not options.resume:
                raise ValueError("output exists")  # noqa: TRY003
            completed_ids = set(existing_ids)
            for index in indexes:
                for kind, request in zip(("review", "report"), pairs[index], strict=True):
                    for repetition in range(options.repetitions):
                        case_id = hashlib.sha256(
                            f"{options.source_path.name}|{index}|{kind}|{repetition}".encode()
                        ).hexdigest()[:16]
                        if case_id in completed_ids:
                            continue
                        started = perf_counter()
                        try:
                            model_process_names: frozenset[str] = (
                                frozenset[str]({"ollama", "ollama.exe"})
                                if arm_name == "local_rag"
                                else frozenset()
                            )
                            async with asyncio.timeout(90):
                                draft, latency, peak = await measure_draft(
                                    assistant, request, model_process_names=model_process_names
                                )
                            arm_rows.append(
                                {
                                    "case_id": case_id,
                                    "row_index": index,
                                    "kind": kind,
                                    "repetition": repetition,
                                    "latency_s": latency,
                                    "peak_ram_bytes": peak,
                                    "error": None,
                                    **_checks(draft, request),
                                }
                            )
                        except Exception as error:
                            arm_rows.append(
                                {
                                    "case_id": case_id,
                                    "row_index": index,
                                    "kind": kind,
                                    "repetition": repetition,
                                    "latency_s": perf_counter() - started,
                                    "error": type(error).__name__,
                                }
                            )
                        result_path.write_text(
                            "".join(
                                json.dumps(row, ensure_ascii=False) + "\n" for row in arm_rows
                            ),
                            encoding="utf-8",
                        )
            results[arm_name] = arm_rows

    checks = (
        "schema_valid",
        "citation_ids_valid",
        "claim_quotes_literal",
        "hypothesis_observations_literal",
        "source_scope_valid",
        "no_cause_marked_confirmed",
    )
    arms_summary: dict[str, Any] = {}
    for name, rows in results.items():
        successful = [row for row in rows if row["error"] is None]
        latencies = [float(row["latency_s"]) for row in successful]
        field_tp = sum(int(row["field_tp"]) for row in successful)
        field_fp = sum(int(row["field_fp"]) for row in successful)
        field_fn = sum(int(row["field_fn"]) for row in successful)
        field_precision = field_tp / (field_tp + field_fp) if field_tp + field_fp else None
        field_recall = field_tp / (field_tp + field_fn) if field_tp + field_fn else None
        field_f1 = (
            2 * field_precision * field_recall / (field_precision + field_recall)
            if field_precision is not None and field_recall is not None
            and field_precision + field_recall > 0
            else None
        )
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(int(row["row_index"]), str(row["kind"]))].append(row)
        eligible_groups = [
            group for group in grouped.values()
            if len(group) == options.repetitions
            and all(row["error"] is None for row in group)
        ]
        consistent_groups = sum(
            len({row["output_signature"] for row in group}) == 1
            for group in eligible_groups
        )
        by_kind: dict[str, Any] = {}
        for kind in ("review", "report"):
            kind_rows = [row for row in successful if row["kind"] == kind]
            kind_latencies = [float(row["latency_s"]) for row in kind_rows]
            by_kind[kind] = {
                "successful_cases": len(kind_rows),
                "mean_latency_s": (
                    sum(kind_latencies) / len(kind_latencies) if kind_latencies else None
                ),
                "p95_latency_s": _p95(kind_latencies) if kind_latencies else None,
            }
        arms_summary[name] = {
            "cases": len(rows),
            "failures": len(rows) - len(successful),
            "checks": {check: sum(bool(row.get(check)) for row in successful) for check in checks},
            "mean_latency_s": sum(latencies) / len(latencies) if latencies else None,
            "p95_latency_s": _p95(latencies) if latencies else None,
            "hypothesis_rate": (
                sum(int(row["four_m_hypotheses"]) > 0 for row in successful) / len(successful)
                if successful
                else None
            ),
            "field_metric_scope": (
                "exact literal item_description and requisition_comment fields only"
            ),
            "field_tp": field_tp,
            "field_fp": field_fp,
            "field_fn": field_fn,
            "field_accuracy": field_tp / (field_tp + field_fn) if field_tp + field_fn else None,
            "field_precision": field_precision,
            "field_recall": field_recall,
            "field_f1": field_f1,
            "completion_tokens_total": sum(int(row["completion_tokens"]) for row in successful),
            "model_generation_tokens_per_s": (
                sum(int(row["completion_tokens"]) for row in successful)
                / sum(float(row["model_duration_s"]) for row in successful
                      if float(row["model_duration_s"]) > 0)
                if any(float(row["model_duration_s"]) > 0 for row in successful)
                else None
            ),
            "generation_tokens_per_s_note": (
                "completion tokens divided by summed Ollama total_duration_s; "
                "includes model-side prompt processing"
            ),
            "mean_generation_tokens_per_s": (
                sum(float(row["generation_tokens_per_s"]) for row in successful
                    if row.get("generation_tokens_per_s") is not None)
                / sum(row.get("generation_tokens_per_s") is not None for row in successful)
                if any(row.get("generation_tokens_per_s") is not None for row in successful)
                else None
            ),
            "peak_process_ram_gb": max(
                (int(row["peak_ram_bytes"]) for row in successful), default=0
            ) / 1_000_000_000,
            "repeat_consistency": {
                "consistent_groups": consistent_groups,
                "eligible_groups": len(eligible_groups),
                "rate": consistent_groups / len(eligible_groups) if eligible_groups else None,
            },
            "by_kind": by_kind,
        }
    manifest = {
        "benchmark": "hanaro_anonymized_transaction_export",
        "source_name": options.source_path.name,
        "source_sha256": hashlib.sha256(options.source_path.read_bytes()).hexdigest(),
        "source_rows_read": len(raw.rows),
        "source_rows_accepted": len(prepared.rows),
        "layout_adherence": prepared.layout.adherence,
        "selected_rows": len(indexes),
        "cases_per_arm": len(indexes) * 2 * options.repetitions,
        "unique_cases_per_arm": len(indexes) * 2,
        "repetitions": options.repetitions,
        "per_case_timeout_s": 90,
        "resumed_existing_results": options.resume,
        "selected_row_indices": list(indexes),
        "model": settings.ollama.llm_model,
        "arms": arms_summary,
        "unscored": [
            "4M cause precision/recall: no human-reviewed cause labels in source export",
            "narrative usefulness: requires blind analyst review",
        ],
        "note": (
            "Structural/evidence-integrity benchmark on real anonymized rows; "
            "not a causal-accuracy benchmark."
        ),
    }
    (options.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
