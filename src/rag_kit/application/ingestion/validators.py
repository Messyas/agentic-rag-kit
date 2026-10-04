"""Composable row validation chain for tabular source ingestion."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict


class RowIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_index: int
    column: str | None
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


class RowValidator(Protocol):
    @property
    def name(self) -> str: ...

    def validate(self, row: Mapping[str, Any], row_index: int) -> list[RowIssue]: ...


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    valid_row_indexes: tuple[int, ...]
    issues: tuple[RowIssue, ...]

    @property
    def valid_row_count(self) -> int:
        return len(self.valid_row_indexes)


class ValidatorChain:
    def __init__(self, validators: Sequence[RowValidator]) -> None:
        self._validators = tuple(validators)

    def run(self, rows: Sequence[Mapping[str, Any]]) -> ValidationOutcome:
        accepted: list[int] = []
        issues: list[RowIssue] = []
        for row_index, row in enumerate(rows):
            row_issues = self._issues_for(row, row_index)
            issues.extend(row_issues)
            if not any(issue.severity == "error" for issue in row_issues):
                accepted.append(row_index)
        return ValidationOutcome(tuple(accepted), tuple(issues))

    def _issues_for(self, row: Mapping[str, Any], row_index: int) -> list[RowIssue]:
        return [
            issue for validator in self._validators for issue in validator.validate(row, row_index)
        ]


@dataclass(frozen=True, slots=True)
class RequiredValidator:
    columns: tuple[str, ...]
    name: str = "required"

    def validate(self, row: Mapping[str, Any], row_index: int) -> list[RowIssue]:
        return [
            RowIssue(
                row_index=row_index,
                column=column,
                code="required",
                message=f"required value {column!r} is missing",
            )
            for column in self.columns
            if row.get(column) is None or str(row.get(column)).strip() == ""
        ]


@dataclass(frozen=True, slots=True)
class TypeValidator:
    columns: Mapping[str, str]
    name: str = "type"

    def validate(self, row: Mapping[str, Any], row_index: int) -> list[RowIssue]:
        issues: list[RowIssue] = []
        for column, expected_type in self.columns.items():
            value = row.get(column)
            if value is None or str(value).strip() == "":
                continue
            try:
                parse_value(value, expected_type)
            except (ValueError, InvalidOperation, TypeError):
                issues.append(
                    RowIssue(
                        row_index=row_index,
                        column=column,
                        code="type",
                        message=f"value does not match {expected_type}",
                    )
                )
        return issues


def parse_value(value: Any, expected_type: str) -> Any:  # noqa: PLR0911
    """Parse supported common types, including decimal numbers in pt-BR format."""
    if expected_type == "str":
        return str(value)
    if expected_type in {"int", "float", "decimal"}:
        return _parse_number(value, expected_type)
    if expected_type == "date":
        return _parse_date(value)
    if expected_type == "datetime":
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if expected_type == "bool":
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1", "sim", "yes"}:
            return True
        if normalized in {"false", "0", "não", "nao", "no"}:
            return False
        raise ValueError("invalid boolean")  # noqa: TRY003
    raise ValueError(f"unsupported type: {expected_type}")  # noqa: TRY003


def _parse_number(value: Any, expected_type: str) -> int | float | Decimal:
    text = str(value).strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    number = Decimal(text)
    if not number.is_finite() or (expected_type == "int" and number != number.to_integral_value()):
        raise ValueError("numeric value must be finite and match the requested type")  # noqa: TRY003
    return (
        int(number)
        if expected_type == "int"
        else float(number)
        if expected_type == "float"
        else number
    )


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    return datetime.strptime(text, "%d/%m/%Y").date() if "/" in text else date.fromisoformat(text)
