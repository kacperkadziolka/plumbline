from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset
from app.infrastructure.db.repositories import (
    FxInput,
    FxRepository,
    HoldingsRepository,
    PositionInput,
    PriceInput,
    PricesRepository,
)

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


# PricesRepository — get_assets_by_tickers tests


async def test_get_assets_by_tickers_returns_matching_assets(session: AsyncSession) -> None:
    session.add(Asset(ticker="AAPL", currency="USD", asset_type="equity"))
    session.add(Asset(ticker="GOOGL", currency="USD", asset_type="equity"))
    await session.flush()

    repo = PricesRepository(session)
    result = await repo.get_assets_by_tickers({"AAPL", "GOOGL", "MISSING"})

    assert set(result.keys()) == {"AAPL", "GOOGL"}


async def test_get_assets_by_tickers_returns_empty_for_no_tickers(session: AsyncSession) -> None:
    repo = PricesRepository(session)
    result = await repo.get_assets_by_tickers(set())

    assert result == {}


# PricesRepository — upsert_prices tests


async def test_upsert_prices_inserts_new_rows(session: AsyncSession) -> None:
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    session.add(asset)
    await session.flush()

    repo = PricesRepository(session)
    prices = [PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150.00"), currency="USD")]
    count = await repo.upsert_prices(prices, {"AAPL": asset})
    await session.commit()

    assert count == 1
    result = await repo.get_prices("AAPL")
    assert len(result) == 1
    assert result[0].close == Decimal("150.00")
    assert result[0].currency == "USD"


async def test_upsert_prices_updates_on_conflict(session: AsyncSession) -> None:
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    session.add(asset)
    await session.flush()

    repo = PricesRepository(session)

    # First insert
    prices1 = [PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150.00"), currency="USD")]
    await repo.upsert_prices(prices1, {"AAPL": asset})
    await session.commit()

    # Upsert with new price
    prices2 = [PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("155.00"), currency="USD")]
    await repo.upsert_prices(prices2, {"AAPL": asset})
    await session.commit()

    result = await repo.get_prices("AAPL")
    assert len(result) == 1
    assert result[0].close == Decimal("155.00")


async def test_upsert_prices_empty_list(session: AsyncSession) -> None:
    repo = PricesRepository(session)
    count = await repo.upsert_prices([], {})

    assert count == 0


# PricesRepository — get_prices tests


async def test_get_prices_with_date_range(session: AsyncSession) -> None:
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    session.add(asset)
    await session.flush()

    repo = PricesRepository(session)
    prices = [
        PriceInput(ticker="AAPL", date=date(2024, 1, 10), close=Decimal("148"), currency="USD"),
        PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150"), currency="USD"),
        PriceInput(ticker="AAPL", date=date(2024, 1, 20), close=Decimal("152"), currency="USD"),
    ]
    await repo.upsert_prices(prices, {"AAPL": asset})
    await session.commit()

    filtered = await repo.get_prices("AAPL", start_date=date(2024, 1, 12), end_date=date(2024, 1, 18))
    assert len(filtered) == 1
    assert filtered[0].date == date(2024, 1, 15)


async def test_get_prices_raises_for_unknown_ticker(session: AsyncSession) -> None:
    repo = PricesRepository(session)

    with pytest.raises(DataMissingError) as exc_info:
        await repo.get_prices("NONEXISTENT")

    assert "NONEXISTENT" in exc_info.value.message


async def test_get_prices_sorted_by_date_ascending(session: AsyncSession) -> None:
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    session.add(asset)
    await session.flush()

    repo = PricesRepository(session)
    prices = [
        PriceInput(ticker="AAPL", date=date(2024, 1, 20), close=Decimal("152"), currency="USD"),
        PriceInput(ticker="AAPL", date=date(2024, 1, 10), close=Decimal("148"), currency="USD"),
        PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150"), currency="USD"),
    ]
    await repo.upsert_prices(prices, {"AAPL": asset})
    await session.commit()

    result = await repo.get_prices("AAPL")
    dates = [p.date for p in result]
    assert dates == sorted(dates)


# FxRepository — upsert_fx_rates tests


async def test_upsert_fx_rates_inserts_new_rows(session: AsyncSession) -> None:
    repo = FxRepository(session)
    rates = [FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.92"))]
    count = await repo.upsert_fx_rates(rates)
    await session.commit()

    assert count == 1
    result = await repo.get_fx_rates("USD/EUR")
    assert len(result) == 1
    assert result[0].rate == Decimal("0.92")


async def test_upsert_fx_rates_updates_on_conflict(session: AsyncSession) -> None:
    repo = FxRepository(session)

    rates1 = [FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.92"))]
    await repo.upsert_fx_rates(rates1)
    await session.commit()

    rates2 = [FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.93"))]
    await repo.upsert_fx_rates(rates2)
    await session.commit()

    result = await repo.get_fx_rates("USD/EUR")
    assert len(result) == 1
    assert result[0].rate == Decimal("0.93")


async def test_upsert_fx_rates_empty_list(session: AsyncSession) -> None:
    repo = FxRepository(session)
    count = await repo.upsert_fx_rates([])

    assert count == 0


# FxRepository — get_fx_rates tests


async def test_get_fx_rates_with_date_range(session: AsyncSession) -> None:
    repo = FxRepository(session)
    rates = [
        FxInput(date=date(2024, 1, 10), pair="USD/EUR", rate=Decimal("0.91")),
        FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.92")),
        FxInput(date=date(2024, 1, 20), pair="USD/EUR", rate=Decimal("0.93")),
    ]
    await repo.upsert_fx_rates(rates)
    await session.commit()

    filtered = await repo.get_fx_rates("USD/EUR", start_date=date(2024, 1, 12), end_date=date(2024, 1, 18))
    assert len(filtered) == 1
    assert filtered[0].date == date(2024, 1, 15)


async def test_get_fx_rates_sorted_by_date_ascending(session: AsyncSession) -> None:
    repo = FxRepository(session)
    rates = [
        FxInput(date=date(2024, 1, 20), pair="USD/EUR", rate=Decimal("0.93")),
        FxInput(date=date(2024, 1, 10), pair="USD/EUR", rate=Decimal("0.91")),
    ]
    await repo.upsert_fx_rates(rates)
    await session.commit()

    result = await repo.get_fx_rates("USD/EUR")
    dates = [r.date for r in result]
    assert dates == sorted(dates)


async def test_get_fx_rates_returns_empty_for_unknown_pair(session: AsyncSession) -> None:
    repo = FxRepository(session)
    result = await repo.get_fx_rates("XXX/YYY")

    assert result == []
