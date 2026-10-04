"""Deterministic column normalization and layout adherence reporting."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rag_kit.domain.errors import ConfigurationError

if TYPE_CHECKING:
    from rag_kit.domain.models import RawTable


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    dtype: str = "str"


@dataclass(frozen=True, slots=True)
class LayoutReport:
    expected: tuple[str, ...]
    found: tuple[str, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]
    extra_columns: tuple[str, ...]
    adherence: float
    match_methods: dict[str, str]


@dataclass(frozen=True, slots=True)
class MappedTable:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    report: LayoutReport


class SchemaMapper:
    def __init__(self, columns: tuple[ColumnSpec, ...]) -> None:
        self._columns = columns
        self._aliases = self._make_aliases(columns)

    def _make_aliases(self, columns: tuple[ColumnSpec, ...]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for column in columns:
            for alias in (column.canonical_name, *column.aliases):
                normalized = normalize_header(alias)
                if normalized in aliases and aliases[normalized] != column.canonical_name:
                    raise ConfigurationError(  # noqa: TRY003
                        f"column alias {alias!r} maps to multiple canonical names"
                    )
                aliases[normalized] = column.canonical_name
        return aliases

    def map(self, table: RawTable) -> MappedTable:
        source_to_target: dict[str, str] = {}
        methods: dict[str, str] = {}
        for source_column in table.columns:
            normalized = normalize_header(source_column)
            target = self._aliases.get(normalized)
            if target is not None:
                source_to_target[source_column] = target
                methods[target] = "alias"
        expected = tuple(column.canonical_name for column in self._columns)
        found = tuple(name for name in expected if name in methods)
        required = {column.canonical_name for column in self._columns if column.required}
        missing_required = tuple(
            name for name in expected if name in required and name not in found
        )
        missing_optional = tuple(
            name for name in expected if name not in required and name not in found
        )
        extra = tuple(name for name in table.columns if name not in source_to_target)
        rows = tuple(
            {source_to_target[key]: value for key, value in row.items() if key in source_to_target}
            for row in table.rows
        )
        adherence = len(found) / len(expected) if expected else 1.0
        report = LayoutReport(
            expected, found, missing_required, missing_optional, extra, adherence, methods
        )
        return MappedTable(found, rows, report)


def normalize_header(value: str) -> str:
    without_marks = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "", without_marks.casefold())
