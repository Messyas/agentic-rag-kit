"""File ingestion orchestration with transparent per-source outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol

from rag_kit.application.ingestion.report import (
    FileIngestionReport,
    IngestionReport,
    create_report,
)
from rag_kit.application.ingestion.schema_map import ColumnSpec, LayoutReport, SchemaMapper
from rag_kit.application.ingestion.validators import (
    RequiredValidator,
    TypeValidator,
    ValidationOutcome,
    ValidatorChain,
    parse_value,
)
from rag_kit.domain.errors import IngestionError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from rag_kit.domain.models import RawTable


class _Loader(Protocol):
    def load(self, path: Path) -> RawTable: ...


class IngestionPipeline:
    def __init__(
        self,
        loaders: Mapping[str, _Loader],
        mapper: SchemaMapper,
        validators: ValidatorChain,
    ) -> None:
        self._loaders = {extension.casefold(): loader for extension, loader in loaders.items()}
        self._mapper = mapper
        self._validators = validators

    def run(self, paths: Sequence[Path]) -> IngestionReport:
        started = perf_counter()
        results = tuple(self._process(path) for path in paths)
        return create_report(results, perf_counter() - started)

    def _process(self, path: Path) -> FileIngestionReport:
        loader = self._loaders.get(path.suffix.casefold())
        if loader is None:
            return self._rejected(path, "no loader registered for file extension")
        try:
            raw_table = loader.load(path)
        except IngestionError as exc:
            return self._rejected(path, str(exc))
        mapped = self._mapper.map(raw_table)
        validation = self._validators.run(mapped.rows)
        return FileIngestionReport(
            source_name=raw_table.source_name,
            read=True,
            rows_read=len(mapped.rows),
            valid_rows=validation.valid_row_count,
            layout_adherence=mapped.report.adherence,
        )

    def _rejected(self, path: Path, reason: str) -> FileIngestionReport:
        return FileIngestionReport(
            source_name=str(path),
            read=False,
            rows_read=0,
            valid_rows=0,
            layout_adherence=0.0,
            rejected_reason=reason,
        )


@dataclass(frozen=True, slots=True)
class PreparedTable:
    rows: tuple[dict[str, Any], ...]
    layout: LayoutReport
    validation: ValidationOutcome


def prepare_table(table: RawTable, columns: Sequence[ColumnSpec]) -> PreparedTable:
    """Normalize accepted rows while preserving source fields and quality lineage."""
    mapped = SchemaMapper(tuple(columns)).map(table)
    validators = ValidatorChain(
        (
            RequiredValidator(
                tuple(column.canonical_name for column in columns if column.required)
            ),
            TypeValidator({column.canonical_name: column.dtype for column in columns}),
        )
    )
    validation = validators.run(mapped.rows)
    rows: list[dict[str, Any]] = []
    for index in validation.valid_row_indexes:
        row = {**table.rows[index], **mapped.rows[index]}
        for column in columns:
            value = row.get(column.canonical_name)
            if value is not None and str(value).strip():
                row[column.canonical_name] = parse_value(value, column.dtype)
        rows.append(row)
    return PreparedTable(tuple(rows), mapped.report, validation)
