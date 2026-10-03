"""Smoke test for rag_kit packaging and basic imports."""

import rag_kit


def test_rag_kit_import() -> None:
    assert rag_kit is not None
