"""Evaluation schemas and referentially safe JSONL loading."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path

CaseKind = Literal["answerable", "unanswerable", "prompt_injection", "layout_variant"]


class ExpectedToolUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    required_arguments: dict[str, Any] = Field(default_factory=dict)


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["complete", "insufficient_evidence"]
    defect_type: str | None = None
    required_source_ids: list[str] = Field(default_factory=list)
    observed_fields: dict[str, Any] = Field(default_factory=dict)
    figures: dict[str, str | int | float] = Field(default_factory=dict)
    expected_tool_uses: list[ExpectedToolUse] = Field(default_factory=list[ExpectedToolUse])


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    split: Literal["dev", "test"]
    kind: CaseKind
    subject_fields: dict[str, Any]
    subject_kind: str = "scrap_occurrence"
    corpus_document_ids: list[str] = Field(default_factory=list)
    ground_truth: GroundTruth
    tags: list[str] = Field(default_factory=list)


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    text: str
    source_type: str = "scrap_review"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationDataset(BaseModel):
    cases: tuple[EvalCase, ...]
    corpus: tuple[CorpusDocument, ...]
    few_shot_ids: frozenset[str] = frozenset()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read nonblank JSON objects with line-numbered parse errors."""
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path}:{line_number}: expected a JSON object")  # noqa: TRY003
        records.append(cast("dict[str, Any]", value))
    return records


def load_dataset(directory: Path) -> EvaluationDataset:
    """Load corpus, evaluation cases, and excluded prompt examples."""
    cases = tuple(
        EvalCase.model_validate(record) for record in read_jsonl(directory / "eval_cases.jsonl")
    )
    corpus = tuple(
        CorpusDocument.model_validate(record) for record in read_jsonl(directory / "corpus.jsonl")
    )
    few_shot = (
        read_jsonl(directory / "few_shot.jsonl") if (directory / "few_shot.jsonl").exists() else []
    )
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("eval case IDs must be unique")  # noqa: TRY003
    corpus_ids = {document.document_id for document in corpus}
    if len(corpus_ids) != len(corpus):
        raise ValueError("corpus document IDs must be unique")  # noqa: TRY003
    missing = {
        source_id
        for case in cases
        for source_id in (*case.ground_truth.required_source_ids, *case.corpus_document_ids)
        if source_id not in corpus_ids
    }
    if missing:
        raise ValueError(f"ground truth references missing corpus IDs: {sorted(missing)}")  # noqa: TRY003
    if any(
        set(case.ground_truth.required_source_ids) - set(case.corpus_document_ids) for case in cases
    ):
        raise ValueError("ground truth sources must be available in the case corpus")  # noqa: TRY003
    few_shot_ids = frozenset(str(example["example_id"]) for example in few_shot)
    if few_shot_ids & set(ids):
        raise ValueError("few-shot IDs must not overlap evaluation case IDs")  # noqa: TRY003
    if {case.kind for case in cases} != {
        "answerable",
        "unanswerable",
        "prompt_injection",
        "layout_variant",
    }:
        raise ValueError("dataset must cover all four evaluation case kinds")  # noqa: TRY003
    validate_separation(cases, few_shot)
    return EvaluationDataset(cases=cases, corpus=corpus, few_shot_ids=few_shot_ids)


def _case_text(fields: dict[str, Any]) -> str:
    return " ".join(
        re.findall(
            r"\w+",
            " ".join(
                str(value)
                for name, value in sorted(fields.items())
                if name not in {"occurrence_id", "id", "source_line"}
            ).casefold(),
        )
    )


def _near_duplicate(left: str, right: str) -> bool:
    if left == right:
        return True
    left_words, right_words = left.split(), right.split()
    a = {tuple(left_words[index : index + 5]) for index in range(max(0, len(left_words) - 4))}
    b = {tuple(right_words[index : index + 5]) for index in range(max(0, len(right_words) - 4))}
    return bool(a and b) and len(a & b) / len(a | b) >= 0.8  # noqa: PLR2004 - documented near-duplicate threshold


def validate_separation(cases: tuple[EvalCase, ...], examples: list[dict[str, Any]]) -> None:
    """Reject exact duplicates, split overlap, and prompt/evaluation leakage."""
    texts = [_case_text(case.subject_fields) for case in cases]
    if len(texts) != len(set(texts)):
        raise ValueError("evaluation cases contain duplicate normalized input")  # noqa: TRY003
    for index, case in enumerate(cases):
        for other_index in range(index):
            if case.split != cases[other_index].split and _near_duplicate(
                texts[index], texts[other_index]
            ):
                raise ValueError("dev/test inputs contain near duplicates")  # noqa: TRY003
        for example in examples:
            fields: Any = example.get("subject_fields") or example.get("subject") or {}
            if (
                isinstance(fields, dict)
                and fields
                and _near_duplicate(texts[index], _case_text(cast("dict[str, Any]", fields)))
            ):
                raise ValueError("few-shot example overlaps evaluation input")  # noqa: TRY003
