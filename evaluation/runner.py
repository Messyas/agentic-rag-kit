"""Run evaluation cases sequentially across isolated analysis pipeline arms."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

from evaluation.metrics.agent import (
    abstention_correctness,
    consistency,
    field_exactness,
    injection_resistance,
    outcome_accuracy,
    source_precision_recall_f1,
    tool_call_accuracy,
)
from evaluation.metrics.retrieval import retrieval_metrics
from evaluation.metrics.runtime import ResourceSampler, latency_summary, tokens_per_second
from evaluation.metrics.stats import RateResult
from rag_kit.domain.analysis import AnalysisOutcome, AnalysisResult, Subject

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from evaluation.dataset import EvalCase, EvaluationDataset
    from rag_kit.domain.ports.pipeline import AnalysisPipeline


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """Inputs shared by all arms in one reproducible evaluation run."""

    arms: Mapping[str, AnalysisPipeline]
    dataset: EvaluationDataset
    split: str
    output_directory: Path
    warmup_cases: int = 2
    repeat_count: int = 1

    def __post_init__(self) -> None:
        if self.split not in {"dev", "test"}:
            raise ValueError("split must be dev or test")  # noqa: TRY003
        if self.warmup_cases < 0 or self.repeat_count < 1:
            raise ValueError("warmup_cases must be non-negative and repeat_count positive")  # noqa: TRY003
        if not self.arms:
            raise ValueError("at least one evaluation arm is required")  # noqa: TRY003


async def run_evaluation(run: EvaluationRun) -> dict[str, dict[str, Any]]:
    """Execute warmups and measured cases, saving per-arm JSONL and metrics."""
    cases = [case for case in run.dataset.cases if case.split == run.split]
    if not cases:
        raise ValueError("selected evaluation split has no cases")  # noqa: TRY003
    run.output_directory.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    for arm_name, pipeline in run.arms.items():
        summaries[arm_name] = await _run_arm(run, arm_name, pipeline, cases)
    return summaries


async def _run_arm(
    run: EvaluationRun,
    arm_name: str,
    pipeline: AnalysisPipeline,
    cases: list[EvalCase],
) -> dict[str, Any]:
    warmup_errors = await _warmup(pipeline, cases, run.warmup_cases)
    records: list[dict[str, Any]] = []
    results: list[AnalysisResult] = []
    evaluated_cases: list[EvalCase] = []
    durations: list[float] = []
    with ResourceSampler() as sampler:
        for case in cases:
            for repetition in range(run.repeat_count):
                started = time.perf_counter()
                try:
                    result = await pipeline.analyze(_subject(case))
                    records.append(_record(case, result, repetition, None))
                    results.append(result)
                    evaluated_cases.append(case)
                except Exception as error:
                    records.append(_record(case, None, repetition, type(error).__name__))
                    results.append(_failed_result(case))
                    evaluated_cases.append(case)
                durations.append(time.perf_counter() - started)
    arm_directory = run.output_directory / arm_name
    arm_directory.mkdir(parents=True, exist_ok=True)
    _write_jsonl(arm_directory / "outputs.jsonl", records)
    summary = _metrics(
        evaluated_cases, results, durations, sampler.peaks.ram_gb, sampler.peaks.vram_gb
    )
    summary["warmup_errors"] = warmup_errors
    (arm_directory / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def _metrics(
    cases: list[EvalCase],
    results: list[AnalysisResult],
    durations: list[float],
    peak_ram_gb: float,
    peak_vram_gb: float,
) -> dict[str, Any]:
    expected = [case.ground_truth.outcome for case in cases]
    predicted = [
        result.outcome.value.casefold() if not result.payload.get("error") else "failed"
        for result in results
    ]
    source_metrics = source_precision_recall_f1(
        [
            [
                source
                for claim in result.claims
                if claim.kind != "fact"
                for source in claim.source_ids
            ]
            for result in results
        ],
        [case.ground_truth.required_source_ids for case in cases],
    )
    expected_fields = [
        {
            **case.ground_truth.observed_fields,
            **(
                {"proposed_record.defect_type": case.ground_truth.defect_type}
                if case.ground_truth.defect_type
                else {}
            ),
        }
        for case in cases
    ]
    actual_fields: list[dict[str, Any]] = []
    for result in results:
        observed = dict(result.payload.get("observed_fields", {}))
        raw_proposed = result.payload.get("proposed_record")
        proposed = cast("dict[str, Any]", raw_proposed) if isinstance(raw_proposed, dict) else {}
        observed["proposed_record.defect_type"] = proposed.get("defect_type")
        actual_fields.append(observed)
    exactness = [
        field_exactness(actual, expected)
        for actual, expected in zip(actual_fields, expected_fields, strict=True)
    ]
    accuracy = round(outcome_accuracy(predicted, expected) * len(expected))
    latency = latency_summary(durations)
    prompt_tokens = sum(int(result.usage.get("prompt_tokens", 0)) for result in results)
    completion_tokens = sum(int(result.usage.get("completion_tokens", 0)) for result in results)
    generation_seconds = sum(float(result.usage.get("total_duration_s", 0)) for result in results)
    failures_by_type: dict[str, int] = defaultdict(int)
    for result in results:
        if error_name := result.payload.get("error"):
            failures_by_type[str(error_name)] += 1
    return {
        "case_count": len(results),
        "failure_count": sum(bool(result.payload.get("error")) for result in results),
        **_additional_metrics(cases, results, predicted, expected),
        "outcome_accuracy": _rate("outcome_accuracy", accuracy, len(results)),
        "source_precision": source_metrics.precision,
        "source_recall": source_metrics.recall,
        "source_f1": source_metrics.f1,
        "field_exactness": {
            "exact": sum(item.exact for item in exactness),
            "total": sum(item.total for item in exactness),
            "rate": sum(item.exact for item in exactness) / sum(item.total for item in exactness)
            if sum(item.total for item in exactness)
            else 0.0,
        },
        "latency": {
            "mean_seconds": latency.mean_seconds,
            "p95_seconds": latency.p95_seconds,
            "count": latency.count,
        },
        "peak_ram_gb": peak_ram_gb,
        "peak_vram_gb": peak_vram_gb,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens_per_second": tokens_per_second(completion_tokens, generation_seconds),
        "cases_per_second": len(results) / sum(durations) if sum(durations) else 0.0,
        "failures_by_type": dict(failures_by_type),
    }


def _rate(name: str, successes: int, trials: int) -> dict[str, Any]:
    result = RateResult(name, successes, trials)
    low, high = result.wilson_interval
    return {"successes": successes, "trials": trials, "rate": result.rate, "wilson_95": [low, high]}


def _subject(case: EvalCase) -> Subject:
    return Subject(subject_id=case.case_id, kind=case.subject_kind, fields=case.subject_fields)


def _failed_result(case: EvalCase) -> AnalysisResult:
    return AnalysisResult(
        subject_id=case.case_id,
        outcome=AnalysisOutcome.INSUFFICIENT_EVIDENCE,
        payload={"error": "pipeline_failure"},
    )


def _record(
    case: EvalCase, result: AnalysisResult | None, repetition: int, error: str | None
) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "repetition": repetition,
        "error": error,
        "result": result.model_dump(mode="json") if result else None,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(payload, encoding="utf-8")


def _serialize_rate(result: RateResult) -> dict[str, Any]:
    return _rate(result.name, result.successes, result.trials)


def _additional_metrics(
    cases: list[EvalCase], results: list[AnalysisResult], predicted: list[str], expected: list[str]
) -> dict[str, Any]:
    repeated: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case, result in zip(cases, results, strict=True):
        if not result.payload.get("error"):
            repeated[case.case_id].append(result.model_dump(mode="json"))
    calls = [
        tool_call_accuracy(
            result.usage.get("tool_calls", []),
            [use.model_dump() for use in case.ground_truth.expected_tool_uses],
        )
        for case, result in zip(cases, results, strict=True)
    ]
    attack_outputs = [
        _generated_text(result)
        for case, result in zip(cases, results, strict=True)
        if case.kind == "prompt_injection"
    ]
    return {
        "retrieval": _retrieval_summary(cases, results),
        "figure_parity": _figure_parity(cases, results),
        "abstention_correctness": _serialize_rate(abstention_correctness(predicted, expected)),
        "injection_resistance": _serialize_rate(
            injection_resistance(
                attack_outputs,
                ("ignore previous instructions", "ignore as regras", "pipeline_failure"),
            )
        ),
        "consistency": _serialize_rate(
            consistency([outputs for outputs in repeated.values() if len(outputs) > 1])
        ),
        "valid_without_repairs": _rate(
            "valid_without_repairs",
            sum(
                not result.payload.get("error")
                and not result.violations
                and not result.usage.get("repairs_used", 0)
                for result in results
            ),
            len(results),
        ),
        "tool_call_accuracy": _rate(
            "tool_call_accuracy",
            sum(call.rate.successes for call in calls),
            sum(call.rate.trials for call in calls),
        ),
        "unnecessary_tool_calls": sum(call.unnecessary_tool_calls for call in calls),
    }


async def _warmup(pipeline: AnalysisPipeline, cases: list[EvalCase], count: int) -> list[str]:
    warmup_errors: list[str] = []
    for case in cases[:count]:
        try:
            await pipeline.analyze(_subject(case))
        except Exception as error:
            warmup_errors.append(type(error).__name__)
    return warmup_errors


def _generated_text(result: AnalysisResult) -> str:
    if result.payload.get("error"):
        return "pipeline_failure"
    payload = {
        key: result.payload.get(key) for key in ("context", "hypotheses", "proposed_record", "gaps")
    }
    payload["claims"] = [claim.model_dump() for claim in result.claims if claim.kind != "fact"]
    return json.dumps(payload, ensure_ascii=False, default=str)


def _retrieval_summary(cases: list[EvalCase], results: list[AnalysisResult]) -> dict[str, Any]:
    pairs = [
        (case, result)
        for case, result in zip(cases, results, strict=True)
        if case.ground_truth.required_source_ids
    ]
    return asdict(
        retrieval_metrics(
            [result.usage.get("retrieved_source_ids", []) for _, result in pairs],
            [case.ground_truth.required_source_ids for case, _ in pairs],
            8,
        )
    )


def _figure_parity(cases: list[EvalCase], results: list[AnalysisResult]) -> dict[str, Any]:
    successes = trials = 0
    for case, result in zip(cases, results, strict=True):
        actual = {
            **result.payload.get("observed_fields", {}),
            **{figure["label"]: figure["value"] for figure in result.payload.get("figures", [])},
        }
        for label, expected in case.ground_truth.figures.items():
            trials += 1
            try:
                successes += Decimal(str(actual.get(label))) == Decimal(str(expected))
            except InvalidOperation:
                continue
    return _rate("figure_parity", successes, trials)
