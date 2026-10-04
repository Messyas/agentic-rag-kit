"""Brazilian numeric text converts deterministically during row validation."""

from decimal import Decimal

from rag_kit.application.ingestion.validators import parse_value


def test_numeric_validator_parses_brazilian_decimal_amount() -> None:
    assert parse_value("1.240,50", "decimal") == Decimal("1240.50")
