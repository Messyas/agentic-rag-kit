"""Create an XLSX variant of the checked-in synthetic CSV for ingestion demos."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook


def main() -> None:
    source = Path("examples/hanaro_contract/demo_scrap.csv")
    target = Path("evaluation/runs/demo_scrap.xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("workbook has no active worksheet")  # noqa: TRY003
    for row in rows:
        sheet.append(row)
    workbook.save(target)
    print(target)


if __name__ == "__main__":
    main()
