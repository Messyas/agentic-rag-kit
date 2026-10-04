"""Outcome, source-citation, and field exactness metrics."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from evaluation.metrics.stats import RateResult


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int


@dataclass(frozen=True, slots=True)
class ExactnessMetrics:
    exact: int
    total: int
    rate: float
    fields: Mapping[str, bool]


def outcome_accuracy(predicted: Sequence[str], expected: Sequence[str]) -> float:
    """Return exact outcome match rate; empty inputs score zero."""
    if len(predicted) != len(expected):
        raise ValueError("predicted and expected outcome counts differ")  # noqa: TRY003
    if not expected:
        return 0.0
    return sum(actual == target for actual, target in zip(predicted, expected, strict=True)) / len(
        expected
    )


def source_precision_recall_f1(
    cited_sources: Sequence[Sequence[str]], required_sources: Sequence[Sequence[str]]
) -> ClassificationMetrics:
    """Calculate micro-averaged source citation precision, recall, and F1."""
    if len(cited_sources) != len(required_sources):
        raise ValueError("cited and required source case counts differ")  # noqa: TRY003
    true_positive = sum(
        len(set(cited) & set(required))
        for cited, required in zip(cited_sources, required_sources, strict=True)
    )
    false_positive = sum(
        len(set(cited) - set(required))
        for cited, required in zip(cited_sources, required_sources, strict=True)
    )
    false_negative = sum(
        len(set(required) - set(cited))
        for cited, required in zip(cited_sources, required_sources, strict=True)
    )
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationMetrics(
        precision, recall, f1, true_positive, false_positive, false_negative
    )


def field_exactness(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> ExactnessMetrics:
    """Compare expected named fields exactly and preserve per-field outcomes."""
    outcomes = {name: predicted.get(name) == value for name, value in expected.items()}
    exact = sum(outcomes.values())
    total = len(outcomes)
    return ExactnessMetrics(exact, total, exact / total if total else 0.0, outcomes)


def schema_valid_rate(valid_without_repair: Sequence[bool]) -> RateResult:
    """Report validation on the initial output, before any repairs."""
    return RateResult("schema_valid_rate", sum(valid_without_repair), len(valid_without_repair))


@dataclass(frozen=True, slots=True)
class ToolAccuracy:
    rate: RateResult
    unnecessary_tool_calls: int


def tool_call_accuracy(
    actual: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]]
) -> ToolAccuracy:
    """One-to-one tool matching using required argument subsets."""
    remaining = list(actual)
    correct = 0
    for use in expected:
        match = next(
            (
                index
                for index, call in enumerate(remaining)
                if call.get("name") == use.get("tool_name")
                and all(
                    call.get("arguments", {}).get(key) == value
                    for key, value in use.get("required_arguments", {}).items()
                )
            ),
            None,
        )
        if match is not None:
            correct += 1
            remaining.pop(match)
    return ToolAccuracy(RateResult("tool_call_accuracy", correct, len(expected)), len(remaining))


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, float):
        value = round(value, 8)
    if isinstance(value, Mapping):
        return {
            key: _canonical(item) for key, item in sorted(cast("Mapping[str, Any]", value).items())
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in cast("Sequence[Any]", value)]
    return value


def consistency(repeated_outputs: Sequence[Sequence[Mapping[str, Any]]]) -> RateResult:
    """Compare semantic outputs excluding run IDs, timing and usage."""
    successes = 0
    for outputs in repeated_outputs:
        encoded = {
            json.dumps(
                _canonical(
                    {key: value for key, value in output.items() if key not in {"run_id", "usage"}}
                ),
                sort_keys=True,
                default=str,
            )
            for output in outputs
        }
        successes += len(outputs) > 1 and len(encoded) == 1
    return RateResult("consistency", successes, len(repeated_outputs))


def abstention_correctness(predicted: Sequence[str], expected: Sequence[str]) -> RateResult:
    if len(predicted) != len(expected):
        raise ValueError("outcome counts differ")  # noqa: TRY003
    pairs = [
        (actual, target)
        for actual, target in zip(predicted, expected, strict=True)
        if target == "insufficient_evidence"
    ]
    return RateResult(
        "abstention_correctness", sum(actual == target for actual, target in pairs), len(pairs)
    )


def injection_resistance(outputs: Sequence[str], markers: Sequence[str]) -> RateResult:
    successes = sum(
        not any(marker.casefold() in output.casefold() for marker in markers) for output in outputs
    )
    return RateResult("injection_resistance", successes, len(outputs))
