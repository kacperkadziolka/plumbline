from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.valuate_portfolio import valuate_portfolio_for_date
from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset, FxDaily, HoldingsSnapshot, Position, PriceDaily


async def _create_snapshot_with_prices(
    session: AsyncSession,
    *,
    positions: list[tuple[str, str, str, Decimal]],
    prices: list[tuple[str, date, Decimal]],
    fx_rates: list[tuple[date, str, Decimal]] | None = None,
) -> HoldingsSnapshot:
    """Helper to set up test data: assets, snapshot, prices, and optional FX rates."""
    assets: dict[str, Asset] = {}
    for ticker, currency, asset_type, _qty in positions:
        if ticker not in assets:
            asset = Asset(ticker=ticker, currency=currency, asset_type=asset_type)
            session.add(asset)
            assets[ticker] = asset

    await session.flush()

    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 6, 15))
    session.add(snapshot)
    await session.flush()

    for ticker, _currency, _asset_type, qty in positions:
        session.add(Position(snapshot_id=snapshot.id, asset_id=assets[ticker].id, qty=qty))

    for ticker, price_date, close in prices:
        session.add(
            PriceDaily(date=price_date, asset_id=assets[ticker].id, close=close, currency=assets[ticker].currency)
        )

    if fx_rates:
        for fx_date, pair, rate in fx_rates:
            session.add(FxDaily(date=fx_date, pair=pair, rate=rate))

    await session.commit()
    return snapshot


async def test_valuate_portfolio_no_snapshot_raises(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await valuate_portfolio_for_date(date(2024, 6, 15), session)

    assert "No holdings snapshot found" in exc_info.value.message


async def test_valuate_portfolio_eur_only_positions(session: AsyncSession) -> None:
    await _create_snapshot_with_prices(
        session,
        positions=[
            ("SIE.DE", "EUR", "equity", Decimal("10")),
            ("ALV.DE", "EUR", "equity", Decimal("5")),
        ],
        prices=[
            ("SIE.DE", date(2024, 6, 15), Decimal("150.00")),
            ("ALV.DE", date(2024, 6, 15), Decimal("250.00")),
        ],
    )

    result = await valuate_portfolio_for_date(date(2024, 6, 15), session)

    assert result.base_currency == "EUR"
    assert len(result.positions) == 2
    # ALV.DE: 5 * 250 = 1250, SIE.DE: 10 * 150 = 1500
    assert result.total_value == Decimal("2750.00")
    for pos in result.positions:
        assert pos.fx_rate == Decimal("1")


async def test_valuate_portfolio_mixed_currencies(session: AsyncSession) -> None:
    await _create_snapshot_with_prices(
        session,
        positions=[
            ("AAPL", "USD", "equity", Decimal("10")),
            ("SIE.DE", "EUR", "equity", Decimal("5")),
        ],
        prices=[
            ("AAPL", date(2024, 6, 15), Decimal("200.00")),
            ("SIE.DE", date(2024, 6, 15), Decimal("150.00")),
        ],
        fx_rates=[
            (date(2024, 6, 15), "USD/EUR", Decimal("0.90")),
        ],
    )

    result = await valuate_portfolio_for_date(date(2024, 6, 15), session)

    assert len(result.positions) == 2
    # AAPL: 10 * 200 * 0.90 = 1800, SIE.DE: 5 * 150 * 1 = 750
    assert result.total_value == Decimal("2550.000")

    aapl = next(p for p in result.positions if p.ticker == "AAPL")
    assert aapl.fx_rate == Decimal("0.90")
    assert aapl.value_base == Decimal("1800.000")

    sie = next(p for p in result.positions if p.ticker == "SIE.DE")
    assert sie.fx_rate == Decimal("1")
    assert sie.value_base == Decimal("750.00")


async def test_valuate_portfolio_missing_price_error_specifies_ticker(session: AsyncSession) -> None:
    await _create_snapshot_with_prices(
        session,
        positions=[("AAPL", "USD", "equity", Decimal("10"))],
        prices=[],  # No prices!
        fx_rates=[(date(2024, 6, 15), "USD/EUR", Decimal("0.90"))],
    )

    with pytest.raises(DataMissingError) as exc_info:
        await valuate_portfolio_for_date(date(2024, 6, 15), session)

    assert exc_info.value.details is not None
    assert "AAPL" in exc_info.value.details
    assert "2024-06-15" in exc_info.value.details


async def test_valuate_portfolio_missing_fx_error_specifies_pair(session: AsyncSession) -> None:
    await _create_snapshot_with_prices(
        session,
        positions=[("AAPL", "USD", "equity", Decimal("10"))],
        prices=[("AAPL", date(2024, 6, 15), Decimal("200.00"))],
        fx_rates=[],  # No FX rates!
    )

    with pytest.raises(DataMissingError) as exc_info:
        await valuate_portfolio_for_date(date(2024, 6, 15), session)

    assert exc_info.value.details is not None
    assert "USD/EUR" in exc_info.value.details
    assert "2024-06-15" in exc_info.value.details


async def test_valuate_portfolio_result_sorted_by_ticker(session: AsyncSession) -> None:
    await _create_snapshot_with_prices(
        session,
        positions=[
            ("ZZZ", "EUR", "equity", Decimal("1")),
            ("AAA", "EUR", "equity", Decimal("1")),
            ("MMM", "EUR", "equity", Decimal("1")),
        ],
        prices=[
            ("ZZZ", date(2024, 6, 15), Decimal("10")),
            ("AAA", date(2024, 6, 15), Decimal("20")),
            ("MMM", date(2024, 6, 15), Decimal("30")),
        ],
    )

    result = await valuate_portfolio_for_date(date(2024, 6, 15), session)

    tickers = [p.ticker for p in result.positions]
    assert tickers == ["AAA", "MMM", "ZZZ"]
