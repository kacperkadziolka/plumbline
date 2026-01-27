import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset, Base
from app.infrastructure.db.repositories import HoldingsRepository, PositionInput


@pytest.fixture
async def session():
    """Create a fresh database session for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        engine = create_async_engine(db_url, echo=False)
        async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session_factory() as session:
            yield session

        await engine.dispose()


# get_or_create_asset tests


async def test_get_or_create_asset_creates_new_asset(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    asset = await repo.get_or_create_asset("AAPL", "USD", "equity", "Apple Inc.")
    await session.commit()

    assert asset.ticker == "AAPL"
    assert asset.currency == "USD"
    assert asset.asset_type == "equity"
    assert asset.name == "Apple Inc."
    assert asset.id is not None


async def test_get_or_create_asset_returns_existing_asset(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Create asset
    asset1 = await repo.get_or_create_asset("AAPL", "USD", "equity", "Apple Inc.")
    await session.commit()

    # Get same asset again (with different params - should return existing)
    asset2 = await repo.get_or_create_asset("AAPL", "EUR", "bond", "Different Name")
    await session.commit()

    assert asset1.id == asset2.id
    assert asset2.currency == "USD"  # Original values preserved
    assert asset2.name == "Apple Inc."


# get_asset_by_ticker tests


async def test_get_asset_by_ticker_returns_asset_when_found(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Create asset
    await repo.get_or_create_asset("AAPL", "USD", "equity", "Apple Inc.")
    await session.commit()

    # Find it
    asset = await repo.get_asset_by_ticker("AAPL")

    assert asset is not None
    assert asset.ticker == "AAPL"


async def test_get_asset_by_ticker_returns_none_when_not_found(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    asset = await repo.get_asset_by_ticker("NONEXISTENT")

    assert asset is None


# create_snapshot tests


async def test_create_snapshot_with_new_assets(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)
    as_of_date = datetime(2024, 1, 15)
    positions = [
        PositionInput(ticker="AAPL", qty=Decimal("10.5"), currency="USD", asset_type="equity"),
        PositionInput(ticker="GOOGL", qty=Decimal("5.0"), currency="USD", asset_type="equity"),
    ]

    snapshot = await repo.create_snapshot(as_of_date, positions)
    await session.commit()

    assert snapshot.id is not None
    assert snapshot.as_of_date == as_of_date
    assert len(snapshot.positions) == 2

    # Verify positions and assets are loaded
    tickers = {p.asset.ticker for p in snapshot.positions}
    assert tickers == {"AAPL", "GOOGL"}

    quantities = {p.asset.ticker: p.qty for p in snapshot.positions}
    assert quantities["AAPL"] == Decimal("10.5")
    assert quantities["GOOGL"] == Decimal("5.0")


async def test_create_snapshot_with_existing_assets(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Pre-create an asset
    existing_asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name="Apple Inc.")
    session.add(existing_asset)
    await session.commit()
    existing_id = existing_asset.id

    # Create snapshot with existing and new asset
    as_of_date = datetime(2024, 1, 15)
    positions = [
        PositionInput(ticker="AAPL", qty=Decimal("10")),  # Existing
        PositionInput(ticker="GOOGL", qty=Decimal("5")),  # New
    ]

    snapshot = await repo.create_snapshot(as_of_date, positions)
    await session.commit()

    # Verify existing asset was reused
    aapl_position = next(p for p in snapshot.positions if p.asset.ticker == "AAPL")
    assert aapl_position.asset.id == existing_id


async def test_create_snapshot_with_duplicate_tickers(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)
    as_of_date = datetime(2024, 1, 15)
    # Same ticker twice - both positions should reference same asset
    positions = [
        PositionInput(ticker="AAPL", qty=Decimal("10")),
        PositionInput(ticker="AAPL", qty=Decimal("5")),
    ]

    snapshot = await repo.create_snapshot(as_of_date, positions)
    await session.commit()

    assert len(snapshot.positions) == 2
    # Both positions reference same asset
    asset_ids = {p.asset.id for p in snapshot.positions}
    assert len(asset_ids) == 1


async def test_create_snapshot_empty(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)
    as_of_date = datetime(2024, 1, 15)

    snapshot = await repo.create_snapshot(as_of_date, [])
    await session.commit()

    assert snapshot.id is not None
    assert len(snapshot.positions) == 0


# get_snapshot tests


async def test_get_snapshot_returns_snapshot_with_positions_and_assets(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)
    as_of_date = datetime(2024, 1, 15)
    positions = [PositionInput(ticker="AAPL", qty=Decimal("10"))]

    created = await repo.create_snapshot(as_of_date, positions)
    await session.commit()

    # Fetch it back
    snapshot = await repo.get_snapshot(created.id)

    assert snapshot.id == created.id
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].asset.ticker == "AAPL"


async def test_get_snapshot_raises_when_not_found(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    with pytest.raises(DataMissingError) as exc_info:
        await repo.get_snapshot(99999)

    assert "Holdings snapshot not found" in exc_info.value.message
    assert "99999" in str(exc_info.value.details)


# get_latest_snapshot tests


async def test_get_latest_snapshot_returns_most_recent(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Create snapshots out of order
    await repo.create_snapshot(datetime(2024, 1, 10), [PositionInput(ticker="A", qty=Decimal("1"))])
    await repo.create_snapshot(datetime(2024, 1, 20), [PositionInput(ticker="B", qty=Decimal("2"))])
    await repo.create_snapshot(datetime(2024, 1, 15), [PositionInput(ticker="C", qty=Decimal("3"))])
    await session.commit()

    latest = await repo.get_latest_snapshot()

    assert latest is not None
    assert latest.as_of_date == datetime(2024, 1, 20)
    assert latest.positions[0].asset.ticker == "B"


async def test_get_latest_snapshot_returns_none_when_empty(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    latest = await repo.get_latest_snapshot()

    assert latest is None


# list_snapshots tests


async def test_list_snapshots_ordered_by_date_descending(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    await repo.create_snapshot(datetime(2024, 1, 10), [PositionInput(ticker="A", qty=Decimal("1"))])
    await repo.create_snapshot(datetime(2024, 1, 20), [PositionInput(ticker="B", qty=Decimal("2"))])
    await repo.create_snapshot(datetime(2024, 1, 15), [PositionInput(ticker="C", qty=Decimal("3"))])
    await session.commit()

    snapshots = await repo.list_snapshots()

    assert len(snapshots) == 3
    assert snapshots[0].as_of_date == datetime(2024, 1, 20)
    assert snapshots[1].as_of_date == datetime(2024, 1, 15)
    assert snapshots[2].as_of_date == datetime(2024, 1, 10)


async def test_list_snapshots_respects_limit(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    for i in range(5):
        await repo.create_snapshot(datetime(2024, 1, i + 1), [PositionInput(ticker=f"T{i}", qty=Decimal("1"))])
    await session.commit()

    snapshots = await repo.list_snapshots(limit=2)

    assert len(snapshots) == 2


async def test_list_snapshots_returns_empty_list_when_no_snapshots(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    snapshots = await repo.list_snapshots()

    assert snapshots == []


# delete_snapshot tests


async def test_delete_snapshot_deletes_snapshot_and_positions(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Create snapshot with positions
    snapshot = await repo.create_snapshot(
        datetime(2024, 1, 15),
        [
            PositionInput(ticker="AAPL", qty=Decimal("10")),
            PositionInput(ticker="GOOGL", qty=Decimal("5")),
        ],
    )
    await session.commit()
    snapshot_id = snapshot.id

    # Delete it
    await repo.delete_snapshot(snapshot_id)
    await session.commit()

    # Verify it's gone
    with pytest.raises(DataMissingError):
        await repo.get_snapshot(snapshot_id)


async def test_delete_snapshot_does_not_delete_assets(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    # Create snapshot
    snapshot = await repo.create_snapshot(
        datetime(2024, 1, 15),
        [PositionInput(ticker="AAPL", qty=Decimal("10"))],
    )
    await session.commit()

    # Delete snapshot
    await repo.delete_snapshot(snapshot.id)
    await session.commit()

    # Asset should still exist
    asset = await repo.get_asset_by_ticker("AAPL")
    assert asset is not None


async def test_delete_snapshot_raises_when_not_found(session: AsyncSession) -> None:
    repo = HoldingsRepository(session)

    with pytest.raises(DataMissingError) as exc_info:
        await repo.delete_snapshot(99999)

    assert "Holdings snapshot not found" in exc_info.value.message
