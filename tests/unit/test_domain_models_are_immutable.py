"""Domain value objects reject accidental mutation and produce stable IDs."""

import pytest
from pydantic import ValidationError

from rag_kit.domain.models import Chunk, SourceRef, make_chunk_id


def test_domain_chunk_rejects_mutation_and_unknown_fields() -> None:
    reference = SourceRef(source_type="review", source_id="R1")
    chunk = Chunk(
        chunk_id=make_chunk_id(reference, 0, "texto"), ref=reference, index=0, content="texto"
    )

    with pytest.raises(ValidationError):
        chunk.content = "alterado"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Chunk(chunk_id="x", ref=reference, index=0, content="x", surprise=True)  # type: ignore[call-arg]


def test_chunk_identifier_is_stable_and_content_sensitive() -> None:
    reference = SourceRef(source_type="review", source_id="R1")

    assert make_chunk_id(reference, 0, "texto") == make_chunk_id(reference, 0, "texto")
    assert make_chunk_id(reference, 0, "texto") != make_chunk_id(reference, 0, "texto novo")
