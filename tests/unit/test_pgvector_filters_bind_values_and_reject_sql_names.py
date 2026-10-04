"""Postgres filter compilation binds values and rejects injected identifiers."""

import pytest

from rag_kit.domain.errors import StoreError
from rag_kit.domain.models import MetadataFilter
from rag_kit.infrastructure.persistence.pgvector.filters import compile_filters
from rag_kit.infrastructure.persistence.pgvector.lexical import build_or_tsquery


def test_pgvector_filter_compilation_binds_filter_values() -> None:
    compiled = compile_filters((MetadataFilter(field="factory", value="F1' OR true --"),))

    assert "F1' OR true" not in compiled.sql_fragment
    assert compiled.bind_parameters["filter_0"] == "F1' OR true --"


def test_pgvector_filter_compilation_rejects_sql_identifier_injection() -> None:
    with pytest.raises(StoreError):
        compile_filters((MetadataFilter(field="factory; DROP TABLE chunks", value="F1"),))


def test_lexical_query_uses_unique_or_terms_and_drops_short_tokens() -> None:
    assert build_or_tsquery("danificados no painel danificados") == "danificados | painel"
