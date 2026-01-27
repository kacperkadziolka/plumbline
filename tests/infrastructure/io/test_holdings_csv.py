from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.infrastructure.io.holdings_csv import parse_holdings_csv

# Valid CSV tests


def test_parse_valid_csv_with_all_columns():
    """Parse CSV with all required and optional columns."""
    csv_text = """ticker,qty,currency,asset_type,name
AAPL,10.5,USD,equity,Apple Inc.
GOOGL,5,USD,equity,Alphabet Inc."""

    result = parse_holdings_csv(csv_text)

    assert len(result) == 2
    assert result[0].ticker == "AAPL"
    assert result[0].qty == Decimal("10.5")
    assert result[0].currency == "USD"
    assert result[0].asset_type == "equity"
    assert result[0].name == "Apple Inc."


def test_parse_valid_csv_without_optional_name():
    """Parse CSV without optional name column."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,10,USD,equity"""

    result = parse_holdings_csv(csv_text)

    assert len(result) == 1
    assert result[0].name is None


def test_parse_normalizes_ticker_to_uppercase():
    """Ticker values are normalized to uppercase."""
    csv_text = """ticker,qty,currency,asset_type
aapl,10,USD,equity
Googl,5,USD,equity"""

    result = parse_holdings_csv(csv_text)

    assert result[0].ticker == "AAPL"
    assert result[1].ticker == "GOOGL"


def test_parse_strips_whitespace():
    """All values have whitespace stripped."""
    csv_text = """ticker,qty,currency,asset_type
  AAPL  , 10 , USD , equity """

    result = parse_holdings_csv(csv_text)

    assert result[0].ticker == "AAPL"
    assert result[0].qty == Decimal("10")
    assert result[0].currency == "USD"
    assert result[0].asset_type == "equity"


def test_parse_returns_sorted_by_ticker():
    """Output is sorted by ticker for determinism."""
    csv_text = """ticker,qty,currency,asset_type
ZZZZ,1,EUR,equity
AAAA,2,EUR,equity
MMMM,3,EUR,equity"""

    result = parse_holdings_csv(csv_text)

    assert [r.ticker for r in result] == ["AAAA", "MMMM", "ZZZZ"]


def test_parse_handles_decimal_quantities():
    """Decimal quantities are preserved exactly."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,10.123456789,USD,equity"""

    result = parse_holdings_csv(csv_text)

    assert result[0].qty == Decimal("10.123456789")


def test_parse_handles_case_insensitive_headers():
    """Column headers are case-insensitive."""
    csv_text = """TICKER,QTY,Currency,Asset_Type
AAPL,10,USD,equity"""

    result = parse_holdings_csv(csv_text)

    assert result[0].ticker == "AAPL"


def test_parse_header_only_returns_empty_list():
    """Header-only CSV returns empty list."""
    csv_text = """ticker,qty,currency,asset_type"""

    result = parse_holdings_csv(csv_text)

    assert result == []


# Missing columns tests


def test_parse_raises_for_missing_ticker_column():
    """Raises ValidationError when ticker column is missing."""
    csv_text = """qty,currency,asset_type
10,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "ticker" in exc_info.value.message


def test_parse_raises_for_missing_multiple_columns():
    """Raises ValidationError listing all missing columns."""
    csv_text = """ticker
AAPL"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Missing required columns" in exc_info.value.message
    assert "qty" in exc_info.value.message
    assert "currency" in exc_info.value.message
    assert "asset_type" in exc_info.value.message


# Invalid quantity tests


def test_parse_raises_for_non_numeric_qty():
    """Raises ValidationError for non-numeric qty."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,invalid,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "qty must be a valid number" in exc_info.value.message
    assert "invalid" in exc_info.value.message


def test_parse_raises_for_zero_qty():
    """Raises ValidationError for zero qty."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,0,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "qty must be greater than 0" in exc_info.value.message


def test_parse_raises_for_negative_qty():
    """Raises ValidationError for negative qty."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,-5,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "qty must be greater than 0" in exc_info.value.message


def test_parse_raises_for_empty_qty():
    """Raises ValidationError for empty qty."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "qty cannot be empty" in exc_info.value.message


# Empty ticker tests


def test_parse_raises_for_empty_ticker():
    """Raises ValidationError for empty ticker."""
    csv_text = """ticker,qty,currency,asset_type
,10,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "ticker cannot be empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only_ticker():
    """Raises ValidationError for whitespace-only ticker."""
    csv_text = """ticker,qty,currency,asset_type
   ,10,USD,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "ticker cannot be empty" in exc_info.value.message


# Empty/invalid CSV tests


def test_parse_raises_for_empty_string():
    """Raises ValidationError for empty string input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv("")

    assert "CSV is empty" in exc_info.value.message


def test_parse_raises_for_whitespace_only():
    """Raises ValidationError for whitespace-only input."""
    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv("   \n\n  ")

    assert "CSV is empty" in exc_info.value.message


# Other field validation tests


def test_parse_raises_for_empty_currency():
    """Raises ValidationError for empty currency."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,10,,equity"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "currency cannot be empty" in exc_info.value.message


def test_parse_raises_for_empty_asset_type():
    """Raises ValidationError for empty asset_type."""
    csv_text = """ticker,qty,currency,asset_type
AAPL,10,USD,"""

    with pytest.raises(ValidationError) as exc_info:
        parse_holdings_csv(csv_text)

    assert "Row 2" in exc_info.value.message
    assert "asset_type cannot be empty" in exc_info.value.message


# Determinism test


def test_parse_is_deterministic():
    """Same input always produces identical output."""
    csv_text = """ticker,qty,currency,asset_type
ZZZZ,1,EUR,equity
AAAA,2,EUR,equity
MMMM,3,EUR,equity"""

    result1 = parse_holdings_csv(csv_text)
    result2 = parse_holdings_csv(csv_text)

    assert result1 == result2
    assert [r.ticker for r in result1] == ["AAAA", "MMMM", "ZZZZ"]
