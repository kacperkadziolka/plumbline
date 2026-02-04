from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.infrastructure.io.ibkr_activity_statement import (
    parse_ibkr_activity_statement,
)
from tests.infrastructure.io.ibkr_fixture import EXPECTED_HOLDINGS, REALISTIC_IBKR_CSV

# Sample IBKR Activity Statement CSV content for testing
# Using minimal columns to stay within line length limits
# Type is at index 10: [0]Section,[1]RowType,[2]Cat,[3]Symbol,[4]Desc,[5-9]empty,[10]Type
VALID_IBKR_CSV = (
    "Statement,Header,Field Name,Field Value\n"
    "Statement,Data,BrokerName,Interactive Brokers Ireland Limited\n"
    "Statement,Data,Title,Activity Statement\n"
    "Statement,Data,Period,January 1, 2026 - January 31, 2026\n"
    "Financial Instrument Information,Header,Cat,Symbol,Desc,,,,,,Type,\n"
    "Financial Instrument Information,Data,Stocks,AMZN,AMAZON.COM INC,,,,,,COMMON,\n"
    "Financial Instrument Information,Data,Stocks,CSPX,ISHARES CORE S&P 500,,,,,,ETF,\n"
    "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
    "Open Positions,Data,Summary,Stocks,USD,AMZN,10.5041\n"
    "Open Positions,Data,Summary,Stocks,USD,CSPX,13.4888\n"
    "Open Positions,Total,Stocks,USD,24\n"
)


def test_parse_valid_ibkr_statement() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    assert len(result.holdings) == 2
    # Period is split by comma in CSV, so we only get the first part
    assert result.statement_period == "January 1"


def test_holdings_sorted_by_ticker() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    tickers = [h.ticker for h in result.holdings]
    assert tickers == sorted(tickers)


def test_extracts_correct_ticker_qty_currency() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    amzn = next(h for h in result.holdings if h.ticker == "AMZN")
    assert amzn.qty == Decimal("10.5041")
    assert amzn.currency == "USD"

    cspx = next(h for h in result.holdings if h.ticker == "CSPX")
    assert cspx.qty == Decimal("13.4888")
    assert cspx.currency == "USD"


def test_maps_common_to_equity() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    amzn = next(h for h in result.holdings if h.ticker == "AMZN")
    assert amzn.asset_type == "equity"


def test_maps_etf_type() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    cspx = next(h for h in result.holdings if h.ticker == "CSPX")
    assert cspx.asset_type == "etf"


def test_extracts_asset_names() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    amzn = next(h for h in result.holdings if h.ticker == "AMZN")
    assert amzn.name == "AMAZON.COM INC"

    cspx = next(h for h in result.holdings if h.ticker == "CSPX")
    assert cspx.name == "ISHARES CORE S&P 500"


def test_skips_total_rows() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    # Should only have 2 holdings (Summary rows), not the Total row
    assert len(result.holdings) == 2


def test_handles_missing_financial_instrument_info() -> None:
    csv_without_instrument_info = (
        "Statement,Header,Field Name,Field Value\n"
        "Statement,Data,Period,January 2026\n"
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,AMZN,10\n"
    )
    result = parse_ibkr_activity_statement(csv_without_instrument_info)

    assert len(result.holdings) == 1
    # Without instrument info, falls back to ticker as name and equity as type
    assert result.holdings[0].name == "AMZN"
    assert result.holdings[0].asset_type == "equity"


def test_empty_file_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement("")

    assert "empty" in exc_info.value.message.lower()


def test_missing_open_positions_raises_validation_error() -> None:
    csv_without_positions = "Statement,Header,Field Name,Field Value\nStatement,Data,Period,January 2026\n"
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement(csv_without_positions)

    assert "Open Positions" in exc_info.value.message


def test_empty_open_positions_raises_validation_error() -> None:
    csv_with_empty_positions = (
        "Statement,Header,Field Name,Field Value\n"
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Total,Stocks,USD,0,0,0\n"
    )
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement(csv_with_empty_positions)

    assert "No holdings found" in exc_info.value.message


def test_invalid_quantity_raises_validation_error() -> None:
    csv_with_invalid_qty = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,AMZN,invalid\n"
    )
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement(csv_with_invalid_qty)

    assert "Invalid quantity" in exc_info.value.message


def test_zero_quantity_raises_validation_error() -> None:
    csv_with_zero_qty = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,AMZN,0\n"
    )
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement(csv_with_zero_qty)

    assert "Invalid quantity" in exc_info.value.message


def test_negative_quantity_raises_validation_error() -> None:
    csv_with_negative_qty = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,AMZN,-5\n"
    )
    with pytest.raises(ValidationError) as exc_info:
        parse_ibkr_activity_statement(csv_with_negative_qty)

    assert "Invalid quantity" in exc_info.value.message


def test_handles_fractional_quantities() -> None:
    result = parse_ibkr_activity_statement(VALID_IBKR_CSV)

    amzn = next(h for h in result.holdings if h.ticker == "AMZN")
    # Verify fractional quantity is preserved with full precision
    assert amzn.qty == Decimal("10.5041")


def test_ticker_uppercased() -> None:
    csv_with_lowercase = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,amzn,10\n"
    )
    result = parse_ibkr_activity_statement(csv_with_lowercase)

    assert result.holdings[0].ticker == "AMZN"


def test_currency_uppercased() -> None:
    csv_with_lowercase = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,usd,AMZN,10\n"
    )
    result = parse_ibkr_activity_statement(csv_with_lowercase)

    assert result.holdings[0].currency == "USD"


# Tests using realistic IBKR Activity Statement data
# These tests use the full column structure from actual IBKR exports


class TestRealisticIBKRData:
    """Tests using realistic IBKR Activity Statement format with all columns."""

    def test_parses_all_five_holdings(self) -> None:
        """Verify all 5 positions are extracted from realistic IBKR data."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        assert len(result.holdings) == 5
        tickers = {h.ticker for h in result.holdings}
        assert tickers == {"AMZN", "ASTS", "AXP", "CSPX", "SMH"}

    def test_holdings_match_expected_values(self) -> None:
        """Verify each holding has correct ticker, qty, currency, type, and name."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        holdings_by_ticker = {h.ticker: h for h in result.holdings}

        for expected in EXPECTED_HOLDINGS:
            holding = holdings_by_ticker[expected["ticker"]]
            assert holding.qty == Decimal(expected["qty"])
            assert holding.currency == expected["currency"]
            assert holding.asset_type == expected["asset_type"]
            assert holding.name == expected["name"]

    def test_etfs_correctly_identified(self) -> None:
        """Verify CSPX and SMH are identified as ETFs, others as equity."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        holdings_by_ticker = {h.ticker: h for h in result.holdings}

        # ETFs
        assert holdings_by_ticker["CSPX"].asset_type == "etf"
        assert holdings_by_ticker["SMH"].asset_type == "etf"

        # Equities
        assert holdings_by_ticker["AMZN"].asset_type == "equity"
        assert holdings_by_ticker["ASTS"].asset_type == "equity"
        assert holdings_by_ticker["AXP"].asset_type == "equity"

    def test_fractional_shares_preserved(self) -> None:
        """Verify fractional share quantities are preserved with full precision."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        holdings_by_ticker = {h.ticker: h for h in result.holdings}

        assert holdings_by_ticker["AMZN"].qty == Decimal("10.5041")
        assert holdings_by_ticker["ASTS"].qty == Decimal("6.4284")
        assert holdings_by_ticker["AXP"].qty == Decimal("0.8439")
        assert holdings_by_ticker["CSPX"].qty == Decimal("13.4888")
        assert holdings_by_ticker["SMH"].qty == Decimal("38")

    def test_skips_total_rows_in_realistic_data(self) -> None:
        """Verify Total rows (both USD and EUR) are skipped."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        # Should have exactly 5 holdings, not 7 (which would include Total rows)
        assert len(result.holdings) == 5

    def test_statement_period_extracted(self) -> None:
        """Verify statement period is extracted from realistic data."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        # Period doesn't have comma so full value is extracted
        assert result.statement_period == "January 1 - January 31 2026"

    def test_holdings_sorted_alphabetically(self) -> None:
        """Verify holdings are sorted by ticker for deterministic output."""
        result = parse_ibkr_activity_statement(REALISTIC_IBKR_CSV)

        tickers = [h.ticker for h in result.holdings]
        assert tickers == ["AMZN", "ASTS", "AXP", "CSPX", "SMH"]
