"""Data-only plugin contract for reusable domain packs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from pydantic import BaseModel

    from rag_kit.application.generation.output_guard import OutputGuard
    from rag_kit.application.ingestion.schema_map import ColumnSpec
    from rag_kit.domain.analysis import Claim, Subject
    from rag_kit.domain.models import Document, RetrievalQuery
    from rag_kit.domain.ports.loader import TableLoader
    from rag_kit.domain.ports.retriever import Retriever
    from rag_kit.domain.ports.tool import Tool


def _no_loaders() -> Mapping[str, TableLoader]:
    return {}


def _no_guards() -> Sequence[OutputGuard]:
    return ()


class QueryBuilder(Protocol):
    def build(self, subject: Subject) -> RetrievalQuery: ...


@dataclass(frozen=True, slots=True)
class PackDeps:
    retriever: Retriever
    extras: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PackSpec:
    name: str
    output_model: type[BaseModel]
    prompts_dir: Path
    column_specs: Sequence[ColumnSpec]
    record_to_document: Callable[[Mapping[str, Any]], Document]
    subject_from_record: Callable[[Mapping[str, Any]], Subject]
    query_builder: QueryBuilder
    deterministic_facts: Callable[[Subject], list[Claim]]
    trusted_numbers: Callable[[Subject], Mapping[str, str]]
    build_tools: Callable[[PackDeps], Sequence[Tool]]
    loaders: Mapping[str, TableLoader] = field(default_factory=_no_loaders)
    guards: Callable[[], Sequence[OutputGuard]] = _no_guards

    def validate(self) -> None:
        if not self.name or not self.prompts_dir.is_dir():
            raise ValueError("pack name and prompt directory are required")  # noqa: TRY003 - contextual domain error
        for name in (
            "generator.v1.jinja",
            "grader.v1.jinja",
            "agent_system.v1.jinja",
            "reformulate.v1.jinja",
        ):
            if not (self.prompts_dir / name).is_file():
                raise ValueError(f"pack {self.name}: missing prompt {name}")  # noqa: TRY003 - contextual domain error
        if not callable(getattr(self.output_model, "claims", None)):
            raise TypeError("pack output model must provide claims()")  # noqa: TRY003 - contextual domain error
        if not callable(getattr(self.output_model, "figures_list", None)):
            raise TypeError("pack output model must provide figures_list()")  # noqa: TRY003
        names = [column.canonical_name for column in self.column_specs]
        if len(names) != len(set(names)):
            raise ValueError("pack columns must be unique")  # noqa: TRY003 - contextual domain error
