"""Metrics measuring source file and tabular schema quality."""

from collections.abc import Collection


def file_read_rate(files_read: int, files_received: int) -> float:
    """Fraction of received files that were successfully loaded."""
    return _ratio(files_read, files_received)


def valid_row_rate(valid_rows: int, rows_read: int) -> float:
    """Fraction of loaded rows accepted by validators."""
    return _ratio(valid_rows, rows_read)


def layout_adherence(expected_columns: Collection[str], actual_columns: Collection[str]) -> float:
    """Fraction of expected columns present in a loaded table."""
    if not expected_columns:
        return 1.0
    return len(set(expected_columns) & set(actual_columns)) / len(set(expected_columns))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator < 0 or numerator < 0 or numerator > denominator:
        raise ValueError("metric counts must satisfy 0 <= numerator <= denominator")  # noqa: TRY003
    return numerator / denominator if denominator else 0.0
