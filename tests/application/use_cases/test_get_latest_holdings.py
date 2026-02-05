from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import LatestHoldingsResult, get_latest_holdings
from app.infrastructure.db.models import Asset, HoldingsSnapshot, Position
from app.infrastructure.io.holdings_csv import HoldingRow


async def test_get_latest_holdings_returns_none_when_no_snapshots(session: AsyncSession) -> None:
    """Returns None when no snapshots exist."""
    result = await get_latest_holdings(session)
    assert result is None


async def test_get_latest_holdings_returns_snapshot_data(session: AsyncSession) -> None:
    """Returns correctly structured result for existing snapshot."""
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name="Apple Inc.")
    session.add(asset)
    await session.flush()

    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(snapshot)
    await session.flush()

    position = Position(snapshot_id=snapshot.id, asset_id=asset.id, qty=Decimal("10.5"))
    session.add(position)
    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    assert isinstance(result, LatestHoldingsResult)
    assert result.snapshot_id == snapshot.id
    assert result.as_of_date == datetime(2024, 1, 15)
    assert result.position_count == 1


async def test_get_latest_holdings_returns_correct_positions(session: AsyncSession) -> None:
    """Positions contain correct asset and quantity data."""
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name="Apple Inc.")
    session.add(asset)
    await session.flush()

    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(snapshot)
    await session.flush()

    position = Position(snapshot_id=snapshot.id, asset_id=asset.id, qty=Decimal("10.5"))
    session.add(position)
    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    assert len(result.positions) == 1

    pos = result.positions[0]
    assert isinstance(pos, HoldingRow)
    assert pos.ticker == "AAPL"
    assert pos.name == "Apple Inc."
    assert pos.qty == Decimal("10.5")
    assert pos.currency == "USD"
    assert pos.asset_type == "equity"


async def test_get_latest_holdings_positions_sorted_by_ticker(session: AsyncSession) -> None:
    """Positions are sorted alphabetically by ticker."""
    asset_z = Asset(ticker="ZZZ", currency="USD", asset_type="equity", name=None)
    asset_a = Asset(ticker="AAA", currency="EUR", asset_type="bond", name=None)
    asset_m = Asset(ticker="MMM", currency="GBP", asset_type="equity", name=None)
    session.add_all([asset_z, asset_a, asset_m])
    await session.flush()

    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(snapshot)
    await session.flush()

    session.add(Position(snapshot_id=snapshot.id, asset_id=asset_z.id, qty=Decimal("1")))
    session.add(Position(snapshot_id=snapshot.id, asset_id=asset_a.id, qty=Decimal("2")))
    session.add(Position(snapshot_id=snapshot.id, asset_id=asset_m.id, qty=Decimal("3")))
    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    tickers = [p.ticker for p in result.positions]
    assert tickers == ["AAA", "MMM", "ZZZ"]


async def test_get_latest_holdings_returns_most_recent_snapshot(session: AsyncSession) -> None:
    """Returns the most recent snapshot by as_of_date."""
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name=None)
    session.add(asset)
    await session.flush()

    old_snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 1))
    session.add(old_snapshot)
    await session.flush()
    session.add(Position(snapshot_id=old_snapshot.id, asset_id=asset.id, qty=Decimal("5")))

    new_snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(new_snapshot)
    await session.flush()
    session.add(Position(snapshot_id=new_snapshot.id, asset_id=asset.id, qty=Decimal("10")))

    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    assert result.snapshot_id == new_snapshot.id
    assert result.as_of_date == datetime(2024, 1, 15)
    assert result.positions[0].qty == Decimal("10")


async def test_get_latest_holdings_handles_empty_snapshot(session: AsyncSession) -> None:
    """Returns empty positions list for snapshot with no positions."""
    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(snapshot)
    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    assert result.position_count == 0
    assert result.positions == []


async def test_get_latest_holdings_handles_null_asset_name(session: AsyncSession) -> None:
    """Asset name can be None."""
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name=None)
    session.add(asset)
    await session.flush()

    snapshot = HoldingsSnapshot(as_of_date=datetime(2024, 1, 15))
    session.add(snapshot)
    await session.flush()

    position = Position(snapshot_id=snapshot.id, asset_id=asset.id, qty=Decimal("10"))
    session.add(position)
    await session.commit()

    result = await get_latest_holdings(session)

    assert result is not None
    assert result.positions[0].name is None
