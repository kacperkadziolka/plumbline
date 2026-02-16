import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infrastructure.io.contributions_csv import parse_contributions_csv

# --- Valid CSV tests ---


def test_parse_valid_csv():
    """Parse CSV with all required columns."""
    csv_text = """date,amount,currency
2024-01-15,1000.00,EUR
2024-02-15,1500.50,USD"""

    result = parse_contributions_csv(csv_text)

    assert len(result) == 2
    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].amount == Decimal("1000.00")
    assert result[0].currency == "EUR"
    assert result[1].date == datetime.date(2024, 2, 15)
    assert result[1].amount == Decimal("1500.50")
    assert result[1].currency == "USD"


def test_parse_strips_whitespace():
    """All values have whitespace stripped."""
    csv_text = """date,amount,currency
  2024-01-15  ,  1000  ,  EUR  """

    result = parse_contributions_csv(csv_text)

    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].amount == Decimal("1000")
    assert result[0].currency == "EUR"


def test_parse_normalizes_currency_to_uppercase():
    """Currency values are normalized to uppercase."""
    csv_text = """date,amount,currency
2024-01-15,1000,eur
2024-02-15,1500,Usd"""

    result = parse_contributions_csv(csv_text)

    assert result[0].currency == "EUR"
    assert result[1].currency == "USD"


def test_parse_returns_sorted_by_date():
    """Output is sorted by date for determinism."""
    csv_text = """date,amount,currency
2024-03-15,2000,EUR
2024-01-15,1000,EUR
2024-02-15,1500,EUR"""

    result = parse_contributions_csv(csv_text)

    assert [r.date for r in result] == [
        datetime.date(2024, 1, 15),
        datetime.date(2024, 2, 15),
        datetime.date(2024, 3, 15),
    ]


def test_parse_preserves_decimal_precision():
    """Decimal amounts are preserved exactly."""
    csv_text = """date,amount,currency
2024-01-15,1234.56789,EUR"""

    result = parse_contributions_csv(csv_text)

    assert result[0].amount == Decimal("1234.56789")


def test_parse_handles_case_insensitive_headers():
    """Column headers are case-insensitive."""
    csv_text = """DATE,Amount,CURRENCY
2024-01-15,1000,EUR"""

    result = parse_contributions_csv(csv_text)

    assert result[0].amount == Decimal("1000")


def test_parse_header_only_returns_empty_list():
    """Header-only CSV returns empty list."""
    csv_text = """date,amount,currency"""

    result = parse_contributions_csv(csv_text)

    assert result == []


def test_parse_from_file_path(tmp_path: Path):
    """Parse CSV from file path."""
    csv_file = tmp_path / "contributions.csv"
    csv_file.write_text("date,amount,currency\n2024-01-15,1000,EUR")

    result = parse_contributions_csv(csv_file)

    assert len(result) == 1
    assert result[0].date == datetime.date(2024, 1, 15)
    assert result[0].amount == Decimal("1000")
    assert result[0].currency == "EUR"


# --- Missing columns tests ---


def test_parse_raises_for_missing_single_column():
    """Raises ValidationError when a required column is missing."""
    csv_text = """date,amount
2024-01-15,1000"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "currency" in exc_info.value.message


def test_parse_raises_for_missing_multiple_columns():
    """Raises ValidationError listing all missing columns."""
    csv_text = """date
2024-01-15"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "amount" in exc_info.value.message
    assert "currency" in exc_info.value.message


# --- Amount validation tests ---


def test_parse_raises_for_non_numeric_amount():
    """Raises ValidationError for non-numeric amount."""
    csv_text = """date,amount,currency
2024-01-15,invalid,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "amount must be a valid number" in exc_info.value.message
    assert "invalid" in exc_info.value.message


def test_parse_raises_for_zero_amount():
    """Raises ValidationError for zero amount."""
    csv_text = """date,amount,currency
2024-01-15,0,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "amount must be greater than 0" in exc_info.value.message


def test_parse_raises_for_negative_amount():
    """Raises ValidationError for negative amount."""
    csv_text = """date,amount,currency
2024-01-15,-500,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "amount must be greater than 0" in exc_info.value.message


def test_parse_raises_for_empty_amount():
    """Raises ValidationError for empty amount."""
    csv_text = """date,amount,currency
2024-01-15,,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "amount cannot be empty" in exc_info.value.message


# --- Currency validation tests ---


def test_parse_raises_for_empty_currency():
    """Raises ValidationError for empty currency."""
    csv_text = """date,amount,currency
2024-01-15,1000,"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "currency cannot be empty" in exc_info.value.message


def test_parse_raises_for_currency_too_short():
    """Raises ValidationError for currency code that is too short."""
    csv_text = """date,amount,currency
2024-01-15,1000,EU"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "3-letter code" in exc_info.value.message


def test_parse_raises_for_currency_too_long():
    """Raises ValidationError for currency code that is too long."""
    csv_text = """date,amount,currency
2024-01-15,1000,EURO"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "3-letter code" in exc_info.value.message


def test_parse_raises_for_currency_with_numbers():
    """Raises ValidationError for currency containing numbers."""
    csv_text = """date,amount,currency
2024-01-15,1000,EU1"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "3-letter code" in exc_info.value.message


# --- Date validation tests ---


def test_parse_raises_for_empty_date():
    """Raises ValidationError for empty date."""
    csv_text = """date,amount,currency
,1000,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date cannot be empty" in exc_info.value.message


def test_parse_raises_for_invalid_date_format():
    """Raises ValidationError for invalid date format."""
    csv_text = """date,amount,currency
15-01-2024,1000,EUR"""

    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date must be in YYYY-MM-DD format" in exc_info.value.message


# --- Empty/invalid input tests ---


def test_parse_raises_for_empty_string():
    """Raises ValidationError for empty string input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv("")

    assert "CSV is empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only():
    """Raises ValidationError for whitespace-only input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_contributions_csv("   \n\n  ")

    assert "CSV is empty" in exc_info.value.message


# --- Determinism test ---


def test_parse_is_deterministic():
    """Same input always produces identical output."""
    csv_text = """date,amount,currency
2024-03-15,2000,EUR
2024-01-15,1000,USD
2024-02-15,1500,EUR"""

    result1 = parse_contributions_csv(csv_text)
    result2 = parse_contributions_csv(csv_text)

    assert result1 == result2
    assert [r.date for r in result1] == [
        datetime.date(2024, 1, 15),
        datetime.date(2024, 2, 15),
        datetime.date(2024, 3, 15),
    ]
