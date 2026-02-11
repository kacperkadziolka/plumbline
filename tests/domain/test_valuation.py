from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import DataMissingError
from app.domain.valuation import BASE_CURRENCY, PositionInput, valuate_portfolio


def test_single_position_in_base_currency() -> None:
    positions = [PositionInput(ticker="SIE.DE", currency="EUR", qty=Decimal("10"))]
    prices = {"SIE.DE": Decimal("150.00")}

    result = valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates={})

    assert len(result.positions) == 1
    pv = result.positions[0]
    assert pv.ticker == "SIE.DE"
    assert pv.fx_rate == Decimal("1")
    assert pv.value_local == Decimal("1500.00")
    assert pv.value_base == Decimal("1500.00")
    assert result.total_value == Decimal("1500.00")


def test_single_position_in_foreign_currency() -> None:
    positions = [PositionInput(ticker="AAPL", currency="USD", qty=Decimal("5"))]
    prices = {"AAPL": Decimal("200.00")}
    fx_rates = {"USD/EUR": Decimal("0.92")}

    result = valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates)

    pv = result.positions[0]
    assert pv.value_local == Decimal("1000.00")
    assert pv.value_base == Decimal("920.0000")
    assert pv.fx_rate == Decimal("0.92")
    assert result.total_value == Decimal("920.0000")


def test_multiple_positions_mixed_currencies() -> None:
    positions = [
        PositionInput(ticker="AAPL", currency="USD", qty=Decimal("10")),
        PositionInput(ticker="SIE.DE", currency="EUR", qty=Decimal("5")),
    ]
    prices = {"AAPL": Decimal("200.00"), "SIE.DE": Decimal("150.00")}
    fx_rates = {"USD/EUR": Decimal("0.90")}

    result = valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates)

    assert len(result.positions) == 2
    # AAPL: 10 * 200 * 0.90 = 1800
    aapl = result.positions[0]
    assert aapl.ticker == "AAPL"
    assert aapl.value_base == Decimal("1800.000")
    # SIE.DE: 5 * 150 * 1 = 750
    sie = result.positions[1]
    assert sie.ticker == "SIE.DE"
    assert sie.value_base == Decimal("750.00")
    assert result.total_value == Decimal("2550.000")


def test_positions_sorted_by_ticker() -> None:
    positions = [
        PositionInput(ticker="ZZZ", currency="EUR", qty=Decimal("1")),
        PositionInput(ticker="AAA", currency="EUR", qty=Decimal("1")),
        PositionInput(ticker="MMM", currency="EUR", qty=Decimal("1")),
    ]
    prices = {"ZZZ": Decimal("10"), "AAA": Decimal("20"), "MMM": Decimal("30")}

    result = valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates={})

    tickers = [p.ticker for p in result.positions]
    assert tickers == ["AAA", "MMM", "ZZZ"]


def test_total_equals_sum_of_position_values() -> None:
    positions = [
        PositionInput(ticker="A", currency="USD", qty=Decimal("3")),
        PositionInput(ticker="B", currency="EUR", qty=Decimal("7")),
    ]
    prices = {"A": Decimal("100"), "B": Decimal("50")}
    fx_rates = {"USD/EUR": Decimal("0.85")}

    result = valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates)

    expected_total = sum(p.value_base for p in result.positions)
    assert result.total_value == expected_total


def test_missing_price_raises_data_missing_error() -> None:
    positions = [PositionInput(ticker="AAPL", currency="USD", qty=Decimal("10"))]

    with pytest.raises(DataMissingError) as exc_info:
        valuate_portfolio(date(2024, 6, 15), positions, prices={}, fx_rates={"USD/EUR": Decimal("0.92")})

    assert "AAPL" in str(exc_info.value.details)
    assert "2024-06-15" in str(exc_info.value.details)


def test_missing_fx_rate_raises_data_missing_error() -> None:
    positions = [PositionInput(ticker="AAPL", currency="USD", qty=Decimal("10"))]
    prices = {"AAPL": Decimal("200.00")}

    with pytest.raises(DataMissingError) as exc_info:
        valuate_portfolio(date(2024, 6, 15), positions, prices, fx_rates={})

    assert "USD/EUR" in str(exc_info.value.details)
    assert "2024-06-15" in str(exc_info.value.details)


def test_multiple_missing_data_all_reported() -> None:
    positions = [
        PositionInput(ticker="AAPL", currency="USD", qty=Decimal("10")),
        PositionInput(ticker="TSLA", currency="USD", qty=Decimal("5")),
        PositionInput(ticker="NESN.SW", currency="CHF", qty=Decimal("3")),
    ]

    with pytest.raises(DataMissingError) as exc_info:
        valuate_portfolio(date(2024, 6, 15), positions, prices={}, fx_rates={})

    details = exc_info.value.details
    assert details is not None
    assert "AAPL" in details
    assert "TSLA" in details
    assert "NESN.SW" in details
    assert "USD/EUR" in details
    assert "CHF/EUR" in details


def test_empty_portfolio() -> None:
    result = valuate_portfolio(date(2024, 6, 15), positions=[], prices={}, fx_rates={})

    assert result.positions == []
    assert result.total_value == Decimal("0")
    assert result.as_of_date == date(2024, 6, 15)
    assert result.base_currency == "EUR"


def test_base_currency_constant_is_eur() -> None:
    assert BASE_CURRENCY == "EUR"
