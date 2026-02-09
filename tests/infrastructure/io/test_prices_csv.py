from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infrastructure.io.prices_csv import parse_prices_csv

# Valid CSV tests


def test_parse_valid_csv_with_all_columns():
    """Parse CSV with all required columns."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,185.92,USD
2024-01-15,GOOGL,140.25,USD"""

    result = parse_prices_csv(csv_text)

    assert len(result) == 2
    assert result[0].date == date(2024, 1, 15)
    assert result[0].ticker == "AAPL"
    assert result[0].close == Decimal("185.92")
    assert result[0].currency == "USD"


def test_parse_handles_decimal_prices():
    """Decimal prices are preserved exactly."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,185.123456789,USD"""

    result = parse_prices_csv(csv_text)

    assert result[0].close == Decimal("185.123456789")


def test_parse_handles_case_insensitive_headers():
    """Column headers are case-insensitive."""
    csv_text = """DATE,TICKER,Close,Currency
2024-01-15,AAPL,185.92,USD"""

    result = parse_prices_csv(csv_text)

    assert result[0].ticker == "AAPL"
    assert result[0].close == Decimal("185.92")


def test_parse_header_only_returns_empty_list():
    """Header-only CSV returns empty list."""
    csv_text = """date,ticker,close,currency"""

    result = parse_prices_csv(csv_text)

    assert result == []


# Normalization tests


def test_parse_normalizes_ticker_to_uppercase():
    """Ticker values are normalized to uppercase."""
    csv_text = """date,ticker,close,currency
2024-01-15,aapl,185.92,USD
2024-01-15,Googl,140.25,USD"""

    result = parse_prices_csv(csv_text)

    assert result[0].ticker == "AAPL"
    assert result[1].ticker == "GOOGL"


def test_parse_strips_whitespace():
    """All values have whitespace stripped."""
    csv_text = """date,ticker,close,currency
  2024-01-15  ,  AAPL  , 185.92 , USD """

    result = parse_prices_csv(csv_text)

    assert result[0].date == date(2024, 1, 15)
    assert result[0].ticker == "AAPL"
    assert result[0].close == Decimal("185.92")
    assert result[0].currency == "USD"


# Sorting/determinism tests


def test_parse_returns_sorted_by_date_then_ticker():
    """Output is sorted by (date, ticker) for determinism."""
    csv_text = """date,ticker,close,currency
2024-01-16,AAPL,186.00,USD
2024-01-15,ZZZZ,100.00,USD
2024-01-15,AAPL,185.92,USD
2024-01-16,MMMM,50.00,USD"""

    result = parse_prices_csv(csv_text)

    assert [(r.date, r.ticker) for r in result] == [
        (date(2024, 1, 15), "AAPL"),
        (date(2024, 1, 15), "ZZZZ"),
        (date(2024, 1, 16), "AAPL"),
        (date(2024, 1, 16), "MMMM"),
    ]


def test_parse_is_deterministic():
    """Same input always produces identical output."""
    csv_text = """date,ticker,close,currency
2024-01-16,ZZZZ,100.00,USD
2024-01-15,AAAA,50.00,USD
2024-01-15,MMMM,75.00,USD"""

    result1 = parse_prices_csv(csv_text)
    result2 = parse_prices_csv(csv_text)

    assert result1 == result2
    assert [(r.date, r.ticker) for r in result1] == [
        (date(2024, 1, 15), "AAAA"),
        (date(2024, 1, 15), "MMMM"),
        (date(2024, 1, 16), "ZZZZ"),
    ]


# Missing columns tests


def test_parse_raises_for_missing_date_column():
    """Raises ValidationError when date column is missing."""
    csv_text = """ticker,close,currency
AAPL,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "date" in exc_info.value.message


def test_parse_raises_for_missing_multiple_columns():
    """Raises ValidationError listing all missing columns."""
    csv_text = """ticker
AAPL"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "date" in exc_info.value.message
    assert "close" in exc_info.value.message
    assert "currency" in exc_info.value.message


# Invalid date tests


def test_parse_raises_for_non_date_string():
    """Raises ValidationError for non-date string."""
    csv_text = """date,ticker,close,currency
invalid,AAPL,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date must be in YYYY-MM-DD format" in exc_info.value.message
    assert "invalid" in exc_info.value.message


def test_parse_raises_for_wrong_date_format_dmy():
    """Raises ValidationError for DD-MM-YYYY format."""
    csv_text = """date,ticker,close,currency
15-01-2024,AAPL,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date must be in YYYY-MM-DD format" in exc_info.value.message


def test_parse_raises_for_wrong_date_format_slash():
    """Raises ValidationError for MM/DD/YYYY format."""
    csv_text = """date,ticker,close,currency
01/15/2024,AAPL,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date must be in YYYY-MM-DD format" in exc_info.value.message


def test_parse_raises_for_empty_date():
    """Raises ValidationError for empty date."""
    csv_text = """date,ticker,close,currency
,AAPL,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "date cannot be empty" in exc_info.value.message


# Invalid close tests


def test_parse_raises_for_non_numeric_close():
    """Raises ValidationError for non-numeric close."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,invalid,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "close must be a valid number" in exc_info.value.message
    assert "invalid" in exc_info.value.message


def test_parse_raises_for_zero_close():
    """Raises ValidationError for zero close."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,0,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "close must be greater than 0" in exc_info.value.message


def test_parse_raises_for_negative_close():
    """Raises ValidationError for negative close."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,-5.00,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "close must be greater than 0" in exc_info.value.message


def test_parse_raises_for_empty_close():
    """Raises ValidationError for empty close."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "close cannot be empty" in exc_info.value.message


# Empty/invalid CSV tests


def test_parse_raises_for_empty_string():
    """Raises ValidationError for empty string input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv("")

    assert "CSV is empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only():
    """Raises ValidationError for whitespace-only input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv("   \n\n  ")

    assert "CSV is empty" in exc_info.value.message


# Empty field tests


def test_parse_raises_for_empty_ticker():
    """Raises ValidationError for empty ticker."""
    csv_text = """date,ticker,close,currency
2024-01-15,,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "ticker cannot be empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only_ticker():
    """Raises ValidationError for whitespace-only ticker."""
    csv_text = """date,ticker,close,currency
2024-01-15,   ,185.92,USD"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "ticker cannot be empty" in exc_info.value.message


def test_parse_raises_for_empty_currency():
    """Raises ValidationError for empty currency."""
    csv_text = """date,ticker,close,currency
2024-01-15,AAPL,185.92,"""

    with pytest.raises(ValidationError) as exc_info:
        parse_prices_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "currency cannot be empty" in exc_info.value.message


# File path input test


def test_parse_from_file_path(tmp_path: Path):
    """Parse CSV from file path."""
    csv_file = tmp_path / "prices.csv"
    csv_file.write_text("date,ticker,close,currency\n2024-01-15,AAPL,185.92,USD")

    result = parse_prices_csv(csv_file)

    assert len(result) == 1
    assert result[0].date == date(2024, 1, 15)
    assert result[0].ticker == "AAPL"
    assert result[0].close == Decimal("185.92")
