"""Named ingestion metrics and per-file diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileIngestionReport:
    source_name: str
    read: bool
    rows_read: int
    valid_rows: int
    layout_adherence: float
    rejected_reason: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionReport:
    files_received: int
    files_read: int
    rows_read: int
    valid_rows: int
    file_read_rate: float
    valid_row_rate: float
    layout_adherence: float
    files: tuple[FileIngestionReport, ...]
    duration_seconds: float


def create_report(
    files: tuple[FileIngestionReport, ...], duration_seconds: float
) -> IngestionReport:
    files_read = sum(item.read for item in files)
    rows_read = sum(item.rows_read for item in files)
    valid_rows = sum(item.valid_rows for item in files)
    file_count = len(files)
    read_layouts = [item.layout_adherence for item in files if item.read]
    return IngestionReport(
        files_received=file_count,
        files_read=files_read,
        rows_read=rows_read,
        valid_rows=valid_rows,
        file_read_rate=files_read / file_count if file_count else 0.0,
        valid_row_rate=valid_rows / rows_read if rows_read else 0.0,
        layout_adherence=sum(read_layouts) / len(read_layouts) if read_layouts else 0.0,
        files=files,
        duration_seconds=duration_seconds,
    )
