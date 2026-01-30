from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import HoldingsRepository, PositionInput
from app.infrastructure.io.holdings_csv import HoldingRow, parse_holdings_csv


class ImportHoldingsResult(BaseModel):
    """Result of importing holdings from CSV."""

    snapshot_id: int
    position_count: int
    as_of_date: datetime


def _convert_holdings_to_positions(holdings: list[HoldingRow]) -> list[PositionInput]:
    """Convert HoldingRow list to PositionInput list."""
    return [
        PositionInput(
            ticker=h.ticker,
            qty=h.qty,
            currency=h.currency,
            asset_type=h.asset_type,
            name=h.name,
        )
        for h in holdings
    ]


async def import_holdings_manual(
    source: str | Path,
    as_of_date: datetime,
    session: AsyncSession,
) -> ImportHoldingsResult:
    """Import holdings from CSV and persist to database.

    Orchestrates:
    1. Parsing CSV to HoldingRow list
    2. Converting to PositionInput list
    3. Creating snapshot with positions (assets auto-upserted)

    Note: Does not commit. Caller owns the transaction boundary.

    Args:
        source: CSV content as string or Path to CSV file
        as_of_date: Date the holdings are valid as of
        session: Database session for transaction management

    Returns:
        ImportHoldingsResult with snapshot_id, position_count, as_of_date

    Raises:
        ValidationError: If CSV parsing fails (empty, missing columns, invalid data)
    """
    # 1. Parse CSV (raises ValidationError on invalid input)
    holdings = parse_holdings_csv(source)

    # 2. Convert to position inputs
    positions = _convert_holdings_to_positions(holdings)

    # 3. Create snapshot (handles asset upserts internally)
    repo = HoldingsRepository(session)
    snapshot = await repo.create_snapshot(as_of_date, positions)

    return ImportHoldingsResult(
        snapshot_id=snapshot.id,
        position_count=len(snapshot.positions),
        as_of_date=snapshot.as_of_date,
    )
