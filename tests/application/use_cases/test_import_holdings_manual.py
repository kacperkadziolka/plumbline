from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import ImportHoldingsResult, import_holdings_manual
from app.core.errors import ValidationError
from app.infrastructure.db.models import Asset
from app.infrastructure.db.repositories import HoldingsRepository

VALID_CSV = """ticker,qty,currency,asset_type,name
AAPL,10.5,USD,equity,Apple Inc.
GOOGL,5.0,USD,equity,Alphabet Inc.
MSFT,15.0,USD,equity,Microsoft Corp.
"""

VALID_CSV_TWO_ROWS = """ticker,qty,currency,asset_type,name
AAPL,10.5,USD,equity,Apple Inc.
GOOGL,5.0,USD,equity,Alphabet Inc.
"""

HEADER_ONLY_CSV = """ticker,qty,currency,asset_type,name
"""


async def test_import_holdings_creates_snapshot_with_correct_positions(session: AsyncSession) -> None:
    """Import CSV and verify snapshot has correct positions via get_latest_snapshot."""
    await import_holdings_manual(VALID_CSV, datetime(2024, 1, 15), session)
    await session.commit()

    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()

    assert snapshot is not None
    assert len(snapshot.positions) == 3

    # Verify each position has correct data
    positions_by_ticker = {p.asset.ticker: p for p in snapshot.positions}

    assert positions_by_ticker["AAPL"].qty == Decimal("10.5")
    assert positions_by_ticker["AAPL"].asset.currency == "USD"
    assert positions_by_ticker["AAPL"].asset.asset_type == "equity"
    assert positions_by_ticker["AAPL"].asset.name == "Apple Inc."

    assert positions_by_ticker["GOOGL"].qty == Decimal("5.0")
    assert positions_by_ticker["MSFT"].qty == Decimal("15.0")


async def test_import_holdings_returns_correct_result(session: AsyncSession) -> None:
    """Verify the returned result matches the created snapshot."""
    result = await import_holdings_manual(VALID_CSV_TWO_ROWS, datetime(2024, 1, 15), session)
    await session.commit()

    assert isinstance(result, ImportHoldingsResult)
    assert result.position_count == 2
    assert result.as_of_date == datetime(2024, 1, 15)

    # Verify snapshot_id matches actual snapshot
    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()
    assert result.snapshot_id == snapshot.id


async def test_import_holdings_creates_assets_for_new_tickers(session: AsyncSession) -> None:
    """New tickers should create new assets."""
    await import_holdings_manual(VALID_CSV_TWO_ROWS, datetime(2024, 1, 15), session)
    await session.commit()

    repo = HoldingsRepository(session)
    aapl = await repo.get_asset_by_ticker("AAPL")
    googl = await repo.get_asset_by_ticker("GOOGL")

    assert aapl is not None
    assert googl is not None
    assert aapl.ticker == "AAPL"
    assert googl.ticker == "GOOGL"


async def test_import_holdings_reuses_existing_assets(session: AsyncSession) -> None:
    """Existing assets should be reused, not duplicated."""
    # Pre-create an asset
    existing_asset = Asset(ticker="AAPL", currency="USD", asset_type="equity", name="Apple Inc.")
    session.add(existing_asset)
    await session.commit()
    existing_id = existing_asset.id

    # Import CSV with AAPL
    await import_holdings_manual(VALID_CSV_TWO_ROWS, datetime(2024, 1, 15), session)
    await session.commit()

    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()

    # Position for AAPL should reference original asset
    aapl_position = next(p for p in snapshot.positions if p.asset.ticker == "AAPL")
    assert aapl_position.asset.id == existing_id


async def test_import_holdings_latest_snapshot_returns_imported_snapshot(session: AsyncSession) -> None:
    """After import, get_latest_snapshot returns the new snapshot."""
    as_of_date = datetime(2024, 1, 15)
    await import_holdings_manual(VALID_CSV, as_of_date, session)
    await session.commit()

    repo = HoldingsRepository(session)
    latest = await repo.get_latest_snapshot()

    assert latest is not None
    assert latest.as_of_date == as_of_date
    assert len(latest.positions) == 3


async def test_import_holdings_is_deterministic(session: AsyncSession) -> None:
    """Same input produces same output order (determinism requirement)."""
    # CSV with tickers in non-alphabetical order
    csv = """ticker,qty,currency,asset_type
GOOGL,5,USD,equity
AAPL,10,USD,equity
MSFT,15,USD,equity
"""
    await import_holdings_manual(csv, datetime(2024, 1, 15), session)
    await session.commit()

    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()

    # Positions should be in ticker order (AAPL, GOOGL, MSFT) due to CSV parser sorting
    tickers = [p.asset.ticker for p in snapshot.positions]
    assert tickers == sorted(tickers)


async def test_import_holdings_with_header_only_csv(session: AsyncSession) -> None:
    """Header-only CSV creates empty snapshot."""
    result = await import_holdings_manual(HEADER_ONLY_CSV, datetime(2024, 1, 15), session)
    await session.commit()

    assert result.position_count == 0

    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()
    assert snapshot is not None
    assert len(snapshot.positions) == 0


async def test_import_holdings_with_file_path(session: AsyncSession, tmp_path: Path) -> None:
    """Import works with file Path (not just string)."""
    csv_file = tmp_path / "holdings.csv"
    csv_file.write_text(VALID_CSV_TWO_ROWS)

    result = await import_holdings_manual(csv_file, datetime(2024, 1, 15), session)
    await session.commit()

    assert result.position_count == 2

    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()
    assert len(snapshot.positions) == 2


async def test_import_holdings_raises_validation_error_for_invalid_csv(session: AsyncSession) -> None:
    """ValidationError from parser propagates to caller."""
    invalid_csv = """ticker,qty
AAPL,10
"""  # Missing currency and asset_type columns

    with pytest.raises(ValidationError) as exc_info:
        await import_holdings_manual(invalid_csv, datetime(2024, 1, 15), session)

    assert "Missing required columns" in exc_info.value.message


async def test_import_holdings_raises_validation_error_for_empty_csv(session: AsyncSession) -> None:
    """Empty CSV raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        await import_holdings_manual("", datetime(2024, 1, 15), session)

    assert "CSV is empty" in exc_info.value.message
