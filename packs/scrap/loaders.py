"""Position-aware GERP TSV loading with CP1252 fallback and lineage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_kit.domain.errors import IngestionError
from rag_kit.domain.models import RawTable

if TYPE_CHECKING:
    from pathlib import Path

_FIELDS = (
    "organization_code",
    "account_code",
    "account_description",
    "account_alias",
    "subinventory_group",
    "subinventory_code",
    "warehouse_market",
    "receipt_department",
    "receipt_description",
    "item_code",
    "uit",
    "item_description",
    "item_specification",
    "transaction_date",
    "issue_quantity",
    "issue_price",
    "issue_amount_brl",
    "sales_price",
    "sales_amount",
    "warehouse_keeper",
    "planner",
    "work_order",
    "reason",
    "requisition_reason",
    "requisition_comment",
    "reference",
    "make_item",
    "created_by",
)
_HEADER = (
    "Organization Code",
    "Account",
    "Description",
    "Account Alias",
    "Subinventory Group",
    "Subinventory",
    "W/H Market",
    "Receipt Department",
    "Description",
    "Item",
    "UIT",
    "Item Desc",
    "Item Spec",
    "Transaction Date",
    "Issue Quantity",
    "Issue Price",
    "Issue Amount",
    "Sales Price",
    "Sales Amount",
    "Warehouse Keeper",
    "Planner",
    "Work Order",
    "Reason",
    "REQ Reason",
    "REQ Comment",
    "Reference",
    "Make Item",
    "Created by",
    "",
)
_COMPATIBLE = (
    "Organization",
    "Account",
    "Description",
    "Account Alias",
    "Subinventory Group",
    "Subinventory",
    "Warehouse Market",
    "Receipt Department",
    "Receipt Description",
    "Item",
    "UIT",
    "Description",
    "Item Specification",
    "Transaction Date",
    "Issue Quantity",
    "Issue Price",
    "Issue Amount BRL",
    "Sales Price",
    "Sales Amount BRL",
    "Warehouse Keeper",
    "Planner",
    "Work Order",
    "Reason",
    "REQ Reason",
    "REQ Comment",
    "Reference",
    "Make Item",
    "Created By",
    "",
)
_NULL = frozenset({"", "-", "nan", "n/a", "null", "none"})


def _decode(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestionError("GERP input must use UTF-8 or CP1252")  # noqa: TRY003 - contextual domain error


def _parse_line(line: str, number: int) -> dict[str, object]:
    fields = line.split("\t")
    if len(fields) < len(_HEADER) or fields[-1] != "":
        raise IngestionError(f"GERP row {number} has invalid field count or trailing column")  # noqa: TRY003 - contextual domain error
    expanded = len(fields) > len(_HEADER)
    if expanded:
        fields = [
            *fields[:24],
            " | ".join(part.strip() for part in fields[24:-4] if part.strip()),
            *fields[-4:-1],
        ]
    else:
        fields = fields[:-1]
    values: dict[str, object] = {}
    for name, raw in zip(_FIELDS, fields, strict=True):
        cleaned = raw.replace("\u00a0", " ").strip()
        values[name] = None if cleaned.casefold() in _NULL else cleaned
    values["source_line"] = number
    values["quality_flags"] = ["expanded_req_comment_fields"] if expanded else []
    return values


class GerpTsvLoader:
    def load(self, path: Path) -> RawTable:
        try:
            lines = _decode(path).splitlines()
        except OSError as error:
            raise IngestionError("Cannot read GERP file") from error  # noqa: TRY003 - contextual domain error
        if len(lines) < 2 or tuple(lines[0].split("\t")) not in (_HEADER, _COMPATIBLE):  # noqa: PLR2004 - fixed file/protocol format
            raise IngestionError("GERP header/order does not match a supported layout")  # noqa: TRY003 - contextual domain error
        rows = tuple(_parse_line(line, number) for number, line in enumerate(lines[1:], 2))
        return RawTable(
            columns=(*_FIELDS, "source_line", "quality_flags"), rows=rows, source_name=path.name
        )
