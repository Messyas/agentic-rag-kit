"""Safe SQL predicate construction for retrieval metadata filters."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from rag_kit.domain.errors import StoreError
from rag_kit.domain.models import MetadataFilter

FIELD_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
COLUMN_FIELDS = frozenset({"source_type", "source_id", "source_version"})


def _empty_parameters() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class CompiledFilters:
    sql_fragment: str = ""
    bind_parameters: Mapping[str, Any] = field(default_factory=_empty_parameters)


def compile_filters(filters: Sequence[MetadataFilter], alias: str = "c") -> CompiledFilters:
    compiled = [_compile_one(item, alias, f"filter_{index}") for index, item in enumerate(filters)]
    if not compiled:
        return CompiledFilters()
    fragment = " AND " + " AND ".join(part.sql_fragment for part in compiled)
    parameters = {name: value for part in compiled for name, value in part.bind_parameters.items()}
    return CompiledFilters(fragment, parameters)


def _compile_one(item: MetadataFilter, alias: str, parameter_name: str) -> CompiledFilters:
    if not FIELD_NAME.fullmatch(item.field) or alias != "c":
        raise StoreError(f"invalid filter field {item.field!r}")  # noqa: TRY003
    target = _target_expression(item.field, alias)
    if item.op == "eq":
        return CompiledFilters(f"{target} = :{parameter_name}", {parameter_name: str(item.value)})
    if item.op == "in":
        values = [str(value) for value in item.value]
        return CompiledFilters(f"{target} = ANY(:{parameter_name})", {parameter_name: values})
    comparator = ">=" if item.op == "gte" else "<="
    return CompiledFilters(
        f"({target})::numeric {comparator} :{parameter_name}",
        {parameter_name: item.value},
    )


def _target_expression(field_name: str, alias: str) -> str:
    if field_name in COLUMN_FIELDS:
        return f"{alias}.{field_name}"
    return f"({alias}.metadata ->> '{field_name}')"
