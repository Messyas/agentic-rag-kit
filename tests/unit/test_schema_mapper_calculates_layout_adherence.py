"""Header normalization is deterministic and reports missing required fields."""

from rag_kit.application.ingestion.schema_map import ColumnSpec, SchemaMapper
from rag_kit.domain.models import RawTable


def test_schema_mapper_normalizes_accents_and_flags_missing_fields() -> None:
    table = RawTable(
        columns=("LINHA de Produção", "extra"),
        rows=({"LINHA de Produção": "A02", "extra": "x"},),
        source_name="fixture.csv",
    )
    mapper = SchemaMapper(
        (
            ColumnSpec("production_line", aliases=("linha de producao",), required=True),
            ColumnSpec("quantity", required=True),
        )
    )

    mapped = mapper.map(table)

    assert mapped.columns == ("production_line",)
    assert mapped.report.adherence == 0.5
    assert mapped.report.missing_required == ("quantity",)
    assert mapped.rows[0] == {"production_line": "A02"}
