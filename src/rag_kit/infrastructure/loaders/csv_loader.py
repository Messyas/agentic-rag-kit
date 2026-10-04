"""CSV table loader."""

import csv
import io
from pathlib import Path

from rag_kit.domain.errors import IngestionError
from rag_kit.domain.models import RawTable


class CsvLoader:
    def load(self, path: Path) -> RawTable:
        try:
            text = self._read_text(path)
            dialect = self._dialect(text)
            parsed_rows = list(csv.reader(io.StringIO(text), dialect, strict=True))
            headers = self._headers(parsed_rows[0]) if parsed_rows else []
            rows = tuple(
                dict(zip(headers, values, strict=False))
                for values in parsed_rows[1:]
                if any(value.strip() for value in values)
            )
        except (OSError, UnicodeError, csv.Error) as exc:
            raise IngestionError(f"could not read CSV {path}: {exc}") from exc  # noqa: TRY003
        columns = tuple(headers)
        return RawTable(columns=columns, source_name=str(path), rows=rows)

    def _read_text(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise UnicodeError(f"unsupported text encoding: {path}")  # noqa: TRY003

    def _dialect(self, text: str) -> type[csv.Dialect]:
        sample = text[:8192]
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            return csv.excel

    def _headers(self, headers: list[str]) -> list[str]:
        normalized: list[str] = []
        counts: dict[str, int] = {}
        for index, header in enumerate(headers):
            name = header.strip() or f"column_{index}"
            counts[name] = counts.get(name, 0) + 1
            normalized.append(f"{name}_{counts[name]}" if counts[name] > 1 else name)
        return normalized
