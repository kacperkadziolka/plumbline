from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.import_holdings_ibkr import import_holdings_ibkr
from app.core.errors import ValidationError
from app.infrastructure.db.repositories import HoldingsRepository

VALID_IBKR_CSV = (
    "Statement,Data,Period,January 2026\n"
    "Financial Instrument Information,Header,Cat,Symbol,Desc,,,,,Type,\n"
    "Financial Instrument Information,Data,Stocks,AMZN,AMAZON.COM INC,,,,,COMMON,\n"
    "Financial Instrument Information,Data,Stocks,CSPX,ISHARES CORE S&P 500,,,,,ETF,\n"
    "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
    "Open Positions,Data,Summary,Stocks,USD,AMZN,10\n"
    "Open Positions,Data,Summary,Stocks,EUR,CSPX,5.5\n"
)


@pytest.mark.asyncio
async def test_import_creates_snapshot_with_positions(session: AsyncSession) -> None:
    as_of_date = datetime(2026, 1, 31, tzinfo=UTC)

    result = await import_holdings_ibkr(VALID_IBKR_CSV, as_of_date, session)

    assert result.position_count == 2
    assert result.as_of_date == as_of_date

    # Verify snapshot exists in DB
    repo = HoldingsRepository(session)
    snapshot = await repo.get_snapshot(result.snapshot_id)
    assert len(snapshot.positions) == 2


@pytest.mark.asyncio
async def test_import_creates_assets_with_correct_types(session: AsyncSession) -> None:
    as_of_date = datetime(2026, 1, 31, tzinfo=UTC)

    result = await import_holdings_ibkr(VALID_IBKR_CSV, as_of_date, session)

    repo = HoldingsRepository(session)
    snapshot = await repo.get_snapshot(result.snapshot_id)

    # Find assets by ticker
    positions_by_ticker = {p.asset.ticker: p for p in snapshot.positions}

    assert positions_by_ticker["AMZN"].asset.asset_type == "equity"
    assert positions_by_ticker["AMZN"].asset.name == "AMAZON.COM INC"

    assert positions_by_ticker["CSPX"].asset.asset_type == "etf"
    assert positions_by_ticker["CSPX"].asset.name == "ISHARES CORE S&P 500"


@pytest.mark.asyncio
async def test_import_preserves_quantities(session: AsyncSession) -> None:
    as_of_date = datetime(2026, 1, 31, tzinfo=UTC)

    result = await import_holdings_ibkr(VALID_IBKR_CSV, as_of_date, session)

    repo = HoldingsRepository(session)
    snapshot = await repo.get_snapshot(result.snapshot_id)

    positions_by_ticker = {p.asset.ticker: p for p in snapshot.positions}

    assert positions_by_ticker["AMZN"].qty == Decimal("10")
    assert positions_by_ticker["CSPX"].qty == Decimal("5.5")


@pytest.mark.asyncio
async def test_import_empty_statement_raises_error(session: AsyncSession) -> None:
    as_of_date = datetime(2026, 1, 31, tzinfo=UTC)

    with pytest.raises(ValidationError):
        await import_holdings_ibkr("", as_of_date, session)


@pytest.mark.asyncio
async def test_import_no_positions_raises_error(session: AsyncSession) -> None:
    csv_no_positions = (
        "Statement,Data,Period,January 2026\n"
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
    )
    as_of_date = datetime(2026, 1, 31, tzinfo=UTC)

    with pytest.raises(ValidationError):
        await import_holdings_ibkr(csv_no_positions, as_of_date, session)
