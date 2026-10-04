"""The tabular ingestion path reports layout and row validation rates."""

from pathlib import Path

from rag_kit.application.ingestion.pipeline import IngestionPipeline
from rag_kit.application.ingestion.schema_map import ColumnSpec, SchemaMapper
from rag_kit.application.ingestion.validators import RequiredValidator, ValidatorChain
from rag_kit.infrastructure.loaders.csv_loader import CsvLoader


def test_ingestion_pipeline_reports_read_layout_and_validity(tmp_path: Path) -> None:
    source = tmp_path / "occurrences.csv"
    source.write_text("Linha,Quantidade\nA02,4\n,2\n", encoding="utf-8")
    pipeline = IngestionPipeline(
        {".csv": CsvLoader()},
        SchemaMapper(
            (
                ColumnSpec("line", aliases=("Linha",), required=True),
                ColumnSpec("quantity", aliases=("Quantidade",)),
            )
        ),
        ValidatorChain((RequiredValidator(("line",)),)),
    )

    report = pipeline.run((source, tmp_path / "missing.csv"))

    assert report.files_received == 2
    assert report.files_read == 1
    assert report.file_read_rate == 0.5
    assert report.valid_row_rate == 0.5
    assert report.layout_adherence == 1.0
