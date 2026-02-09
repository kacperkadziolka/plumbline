import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infrastructure.io.fx_csv import parse_fx_csv

# Valid CSV tests


def test_parse_valid_csv():
    """Parse CSV with all required columns."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,0.92
2024-01-15,GBP/EUR,1.17"""

    result = parse_fx_csv(csv_text)

    assert len(result) == 2
    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].pair == "GBP/EUR"
    assert result[0].rate == Decimal("1.17")
    assert result[1].pair == "USD/EUR"
    assert result[1].rate == Decimal("0.92")


def test_parse_strips_whitespace():
    """All values have whitespace stripped."""
    csv_text = """date,pair,rate
  2024-01-15  ,  USD/EUR  ,  0.92  """

    result = parse_fx_csv(csv_text)

    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].pair == "USD/EUR"
    assert result[0].rate == Decimal("0.92")


def test_parse_normalizes_pair_to_uppercase():
    """Pair values are normalized to uppercase."""
    csv_text = """date,pair,rate
2024-01-15,usd/eur,0.92
2024-01-15,Gbp/Eur,1.17"""

    result = parse_fx_csv(csv_text)

    assert result[0].pair == "GBP/EUR"
    assert result[1].pair == "USD/EUR"


def test_parse_returns_sorted_by_date_and_pair():
    """Output is sorted by (date, pair) for determinism."""
    csv_text = """date,pair,rate
2024-01-16,USD/EUR,0.93
2024-01-15,USD/EUR,0.92
2024-01-15,GBP/EUR,1.17"""

    result = parse_fx_csv(csv_text)

    assert [(r.date, r.pair) for r in result] == [
        (datetime.date(2024, 1, 15), "GBP/EUR"),
        (datetime.date(2024, 1, 15), "USD/EUR"),
        (datetime.date(2024, 1, 16), "USD/EUR"),
    ]


def test_parse_preserves_decimal_rate_precision():
    """Decimal rates are preserved exactly."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,0.123456789"""

    result = parse_fx_csv(csv_text)

    assert result[0].rate == Decimal("0.123456789")


def test_parse_handles_case_insensitive_headers():
    """Column headers are case-insensitive."""
    csv_text = """DATE,Pair,RATE
2024-01-15,USD/EUR,0.92"""

    result = parse_fx_csv(csv_text)

    assert result[0].pair == "USD/EUR"


def test_parse_header_only_returns_empty_list():
    """Header-only CSV returns empty list."""
    csv_text = """date,pair,rate"""

    result = parse_fx_csv(csv_text)

    assert result == []


# Missing columns tests


def test_parse_raises_for_missing_single_column():
    """Raises ValidationError when a required column is missing."""
    csv_text = """date,rate
2024-01-15,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "pair" in exc_info.value.message


def test_parse_raises_for_missing_multiple_columns():
    """Raises ValidationError listing all missing columns."""
    csv_text = """date
2024-01-15"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "pair" in exc_info.value.message
    assert "rate" in exc_info.value.message


# Pair validation tests


def test_parse_raises_for_empty_pair():
    """Raises ValidationError for empty pair."""
    csv_text = """date,pair,rate
2024-01-15,,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "pair cannot be empty" in exc_info.value.message


def test_parse_raises_for_pair_without_slash():
    """Raises ValidationError for pair without slash separator."""
    csv_text = """date,pair,rate
2024-01-15,USDEUR,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "pair must be in format XXX/YYY" in exc_info.value.message


def test_parse_raises_for_pair_with_wrong_length():
    """Raises ValidationError for pair with wrong currency code length."""
    csv_text = """date,pair,rate
2024-01-15,US/EUR,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "pair must be in format XXX/YYY" in exc_info.value.message


def test_parse_raises_for_pair_with_numbers():
    """Raises ValidationError for pair containing numbers."""
    csv_text = """date,pair,rate
2024-01-15,US1/EUR,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "pair must be in format XXX/YYY" in exc_info.value.message


# Rate validation tests


def test_parse_raises_for_non_numeric_rate():
    """Raises ValidationError for non-numeric rate."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,invalid"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "rate must be a valid number" in exc_info.value.message
    assert "invalid" in exc_info.value.message


def test_parse_raises_for_zero_rate():
    """Raises ValidationError for zero rate."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,0"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "rate must be greater than 0" in exc_info.value.message


def test_parse_raises_for_negative_rate():
    """Raises ValidationError for negative rate."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,-0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "rate must be greater than 0" in exc_info.value.message


def test_parse_raises_for_empty_rate():
    """Raises ValidationError for empty rate."""
    csv_text = """date,pair,rate
2024-01-15,USD/EUR,"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "rate cannot be empty" in exc_info.value.message


# Date validation tests


def test_parse_raises_for_empty_date():
    """Raises ValidationError for empty date."""
    csv_text = """date,pair,rate
,USD/EUR,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date cannot be empty" in exc_info.value.message


def test_parse_raises_for_invalid_date_format():
    """Raises ValidationError for invalid date format."""
    csv_text = """date,pair,rate
15-01-2024,USD/EUR,0.92"""

    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date must be in YYYY-MM-DD format" in exc_info.value.message


# Empty/invalid input tests


def test_parse_raises_for_empty_string():
    """Raises ValidationError for empty string input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv("")

    assert "CSV is empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only():
    """Raises ValidationError for whitespace-only input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_fx_csv("   \n\n  ")

    assert "CSV is empty" in exc_info.value.message


# Determinism test


def test_parse_is_deterministic():
    """Same input always produces identical output."""
    csv_text = """date,pair,rate
2024-01-16,USD/EUR,0.93
2024-01-15,GBP/EUR,1.17
2024-01-15,USD/EUR,0.92"""

    result1 = parse_fx_csv(csv_text)
    result2 = parse_fx_csv(csv_text)

    assert result1 == result2
    assert [(r.date, r.pair) for r in result1] == [
        (datetime.date(2024, 1, 15), "GBP/EUR"),
        (datetime.date(2024, 1, 15), "USD/EUR"),
        (datetime.date(2024, 1, 16), "USD/EUR"),
    ]


# File path input test


def test_parse_from_file_path(tmp_path: Path):
    """Parse CSV from file path."""
    csv_file = tmp_path / "fx_rates.csv"
    csv_file.write_text("date,pair,rate\n2024-01-15,USD/EUR,0.92")

    result = parse_fx_csv(csv_file)

    assert len(result) == 1
    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].pair == "USD/EUR"
    assert result[0].rate == Decimal("0.92")
