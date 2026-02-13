from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset, Policy
from app.infrastructure.db.repositories import (
    FxInput,
    FxRepository,
    HoldingsRepository,
    PolicyRepository,
    PositionInput,
    PriceInput,
    PricesRepository,
    ProposalRepository,
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


# PricesRepository — get_prices_for_date tests


async def test_get_prices_for_date_returns_matching_prices(session: AsyncSession) -> None:
    asset1 = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    asset2 = Asset(ticker="GOOGL", currency="USD", asset_type="equity")
    session.add_all([asset1, asset2])
    await session.flush()

    repo = PricesRepository(session)
    prices = [
        PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150.00"), currency="USD"),
        PriceInput(ticker="GOOGL", date=date(2024, 1, 15), close=Decimal("140.00"), currency="USD"),
        PriceInput(ticker="AAPL", date=date(2024, 1, 16), close=Decimal("151.00"), currency="USD"),
    ]
    await repo.upsert_prices(prices, {"AAPL": asset1, "GOOGL": asset2})
    await session.commit()

    result = await repo.get_prices_for_date({asset1.id, asset2.id}, date(2024, 1, 15))

    assert len(result) == 2
    assert result[asset1.id].close == Decimal("150.00")
    assert result[asset2.id].close == Decimal("140.00")


async def test_get_prices_for_date_returns_empty_for_no_match(session: AsyncSession) -> None:
    asset = Asset(ticker="AAPL", currency="USD", asset_type="equity")
    session.add(asset)
    await session.flush()

    repo = PricesRepository(session)
    prices = [PriceInput(ticker="AAPL", date=date(2024, 1, 15), close=Decimal("150.00"), currency="USD")]
    await repo.upsert_prices(prices, {"AAPL": asset})
    await session.commit()

    result = await repo.get_prices_for_date({asset.id}, date(2024, 1, 16))

    assert result == {}


async def test_get_prices_for_date_returns_empty_for_empty_input(session: AsyncSession) -> None:
    repo = PricesRepository(session)
    result = await repo.get_prices_for_date(set(), date(2024, 1, 15))

    assert result == {}


# FxRepository — get_fx_rates_for_date tests


async def test_get_fx_rates_for_date_returns_matching_rates(session: AsyncSession) -> None:
    repo = FxRepository(session)
    rates = [
        FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.92")),
        FxInput(date=date(2024, 1, 15), pair="GBP/EUR", rate=Decimal("1.16")),
        FxInput(date=date(2024, 1, 16), pair="USD/EUR", rate=Decimal("0.93")),
    ]
    await repo.upsert_fx_rates(rates)
    await session.commit()

    result = await repo.get_fx_rates_for_date({"USD/EUR", "GBP/EUR"}, date(2024, 1, 15))

    assert len(result) == 2
    assert result["USD/EUR"].rate == Decimal("0.92")
    assert result["GBP/EUR"].rate == Decimal("1.16")


async def test_get_fx_rates_for_date_returns_empty_for_no_match(session: AsyncSession) -> None:
    repo = FxRepository(session)
    rates = [FxInput(date=date(2024, 1, 15), pair="USD/EUR", rate=Decimal("0.92"))]
    await repo.upsert_fx_rates(rates)
    await session.commit()

    result = await repo.get_fx_rates_for_date({"USD/EUR"}, date(2024, 1, 16))

    assert result == {}


async def test_get_fx_rates_for_date_returns_empty_for_empty_input(session: AsyncSession) -> None:
    repo = FxRepository(session)
    result = await repo.get_fx_rates_for_date(set(), date(2024, 1, 15))

    assert result == {}


# PolicyRepository tests


async def test_policy_save_creates_new_policy(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    policy = await repo.save("my-policy", "base_currency: EUR\nbuckets: ...", "abc123hash")
    await session.commit()

    assert policy.id is not None
    assert policy.name == "my-policy"
    assert policy.hash == "abc123hash"
    assert policy.yaml_text == "base_currency: EUR\nbuckets: ..."
    assert policy.created_at is not None


async def test_policy_save_is_idempotent_on_duplicate_hash(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    p1 = await repo.save("my-policy", "yaml-text", "samehash")
    await session.commit()

    p2 = await repo.save("different-name", "yaml-text", "samehash")
    await session.commit()

    assert p1.id == p2.id


async def test_policy_get_by_hash_returns_policy(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    await repo.save("my-policy", "yaml-text", "unique-hash")
    await session.commit()

    found = await repo.get_by_hash("unique-hash")
    assert found is not None
    assert found.name == "my-policy"


async def test_policy_get_by_hash_returns_none_when_not_found(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    found = await repo.get_by_hash("nonexistent")
    assert found is None


async def test_policy_list_versions_returns_all_ordered_by_id_desc(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    await repo.save("p", "yaml1", "hash1")
    await repo.save("p", "yaml2", "hash2")
    await repo.save("p", "yaml3", "hash3")
    await session.commit()

    versions = await repo.list_versions()
    assert len(versions) == 3
    # Newest first (by id desc as fallback for same-second created_at)
    assert versions[0].hash == "hash3"
    assert versions[2].hash == "hash1"


async def test_policy_list_versions_filters_by_name(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    await repo.save("alpha", "yaml1", "hash1")
    await repo.save("beta", "yaml2", "hash2")
    await repo.save("alpha", "yaml3", "hash3")
    await session.commit()

    alpha_versions = await repo.list_versions(name="alpha")
    assert len(alpha_versions) == 2
    assert all(v.name == "alpha" for v in alpha_versions)


async def test_policy_list_versions_respects_limit(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    for i in range(5):
        await repo.save("p", f"yaml{i}", f"hash{i}")
    await session.commit()

    versions = await repo.list_versions(limit=2)
    assert len(versions) == 2


async def test_policy_list_versions_returns_empty_when_none_exist(session: AsyncSession) -> None:
    repo = PolicyRepository(session)

    versions = await repo.list_versions()
    assert versions == []


# ProposalRepository tests


async def _create_policy(session: AsyncSession) -> Policy:
    """Helper to create a policy for proposal FK references."""
    repo = PolicyRepository(session)
    policy = await repo.save("test-policy", "base_currency: EUR\nbuckets: ...", "testhash123")
    await session.flush()
    return policy


async def test_proposal_save_creates_new_proposal(session: AsyncSession) -> None:
    policy = await _create_policy(session)
    repo = ProposalRepository(session)

    proposal = await repo.save(policy.id, Decimal("1000.00"), "EUR", '{"trades": []}')
    await session.commit()

    assert proposal.id is not None
    assert proposal.policy_id == policy.id
    assert proposal.amount == Decimal("1000.00")
    assert proposal.currency == "EUR"
    assert proposal.result_json == '{"trades": []}'
    assert proposal.created_at is not None


async def test_proposal_get_by_id_returns_proposal(session: AsyncSession) -> None:
    policy = await _create_policy(session)
    repo = ProposalRepository(session)

    created = await repo.save(policy.id, Decimal("500.00"), "EUR", '{"trades": []}')
    await session.commit()

    found = await repo.get_by_id(created.id)
    assert found is not None
    assert found.id == created.id
    assert found.amount == Decimal("500.00")


async def test_proposal_get_by_id_returns_none_when_not_found(session: AsyncSession) -> None:
    repo = ProposalRepository(session)

    found = await repo.get_by_id(99999)
    assert found is None


async def test_proposal_list_proposals_ordered_by_id_desc(session: AsyncSession) -> None:
    policy = await _create_policy(session)
    repo = ProposalRepository(session)

    await repo.save(policy.id, Decimal("100"), "EUR", '{"n": 1}')
    await repo.save(policy.id, Decimal("200"), "EUR", '{"n": 2}')
    await repo.save(policy.id, Decimal("300"), "EUR", '{"n": 3}')
    await session.commit()

    proposals = await repo.list_proposals()
    assert len(proposals) == 3
    amounts = [p.amount for p in proposals]
    assert amounts == [Decimal("300"), Decimal("200"), Decimal("100")]


async def test_proposal_list_proposals_respects_limit(session: AsyncSession) -> None:
    policy = await _create_policy(session)
    repo = ProposalRepository(session)

    for i in range(5):
        await repo.save(policy.id, Decimal(str(i * 100)), "EUR", f'{{"n": {i}}}')
    await session.commit()

    proposals = await repo.list_proposals(limit=2)
    assert len(proposals) == 2


async def test_proposal_list_proposals_returns_empty_when_none_exist(session: AsyncSession) -> None:
    repo = ProposalRepository(session)

    proposals = await repo.list_proposals()
    assert proposals == []
