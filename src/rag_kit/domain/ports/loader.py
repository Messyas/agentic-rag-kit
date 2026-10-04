"""Tabular source loading protocol."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from rag_kit.domain.models import RawTable


@runtime_checkable
class TableLoader(Protocol):
    def load(self, path: Path) -> RawTable: ...
