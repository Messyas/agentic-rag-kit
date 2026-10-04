"""Typed output models and deterministic facts for the scrap pack."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, create_model

from rag_kit.domain.analysis import Claim, Subject
from rag_kit.domain.models import Frozen


class Figure(Frozen):
    label: str = Field(max_length=60)
    value: Decimal
    unit: Literal["USD", "BRL", "units", "percent", "count"]


class ContextItem(Frozen):
    statement: str = Field(min_length=5, max_length=400)
    source_ids: list[str] = Field(min_length=1)


class Hypothesis(Frozen):
    statement: str = Field(min_length=5, max_length=400)
    confidence: Literal["low", "medium", "high"]
    source_ids: list[str] = Field(min_length=1)


class GapItem(Frozen):
    question: str = Field(max_length=300)
    evidence_needed: str | None = Field(default=None, max_length=300)


class ProposedRecord(Frozen):
    title: str = Field(max_length=120)
    description: str = Field(max_length=800)
    defect_type: str | None = None


class PreAnalysis(Frozen):
    """LLM-generated context, hypotheses and gaps; observed facts are added in code."""

    outcome: Literal["complete", "insufficient_evidence"]
    context: list[ContextItem] = Field(default_factory=list[ContextItem])
    hypotheses: list[Hypothesis] = Field(default_factory=list[Hypothesis])
    gaps: list[GapItem] = Field(default_factory=list[GapItem])
    proposed_record: ProposedRecord | None = None
    figures: list[Figure] = Field(default_factory=list[Figure])

    def claims(self) -> list[Claim]:
        context = [ContextItem.model_validate(item) for item in self.context]
        hypotheses = [Hypothesis.model_validate(item) for item in self.hypotheses]
        return [
            Claim(kind="context", statement=item.statement, source_ids=tuple(item.source_ids))
            for item in context
        ] + [
            Claim(kind="hypothesis", statement=item.statement, source_ids=tuple(item.source_ids))
            for item in hypotheses
        ]

    def figures_list(self) -> list[tuple[str, Decimal]]:
        figures = [Figure.model_validate(item) for item in self.figures]
        return [(figure.label, figure.value) for figure in figures]


def load_defect_types(path: Path | None = None) -> tuple[str, ...]:
    """Read the controlled vocabulary from its simple YAML sequence."""
    vocabulary_path = path or Path(__file__).with_name("defect_types.yaml")
    values = tuple(
        line.strip()[2:].strip().strip("\"'")
        for line in vocabulary_path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ")
    )
    if not values or "OTHER" not in values:
        raise ValueError(f"{vocabulary_path} must define defect types and OTHER")  # noqa: TRY003
    return values


def build_pre_analysis_model(path: Path | None = None) -> type[PreAnalysis]:
    """Build the pack output schema with the controlled defect vocabulary."""
    defect_types = load_defect_types(path)
    defect_type = Literal.__getitem__(defect_types)  # type: ignore[attr-defined]
    proposed = create_model(
        "ControlledProposedRecord",
        __base__=ProposedRecord,
        defect_type=(defect_type | None, None),
    )
    return create_model(
        "ScrapPreAnalysis",
        __base__=PreAnalysis,
        proposed_record=(proposed | None, None),
    )


_FACT_LABELS = {
    "date": "Data da ocorrência",
    "factory": "Fábrica",
    "line": "Linha",
    "product": "Produto",
    "component": "Componente",
    "quantity": "Quantidade",
    "cost": "Custo",
    "original_description": "Descrição original",
}


def deterministic_facts(subject: Subject) -> list[Claim]:
    """Convert present occurrence fields into stable source-backed facts."""
    occurrence_id = str(subject.fields.get("occurrence_id", subject.subject_id))
    claims: list[Claim] = []
    for field_name, label in _FACT_LABELS.items():
        value = subject.fields.get(field_name)
        if value is None or value == "":
            continue
        claims.append(
            Claim(
                kind="fact",
                statement=f"{label}: {value}",
                source_ids=(occurrence_id,),
            )
        )
    return claims
