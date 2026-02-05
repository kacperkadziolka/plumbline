from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.import_holdings_manual import (
    ImportHoldingsResult,
    _convert_holdings_to_positions,
)
from app.infrastructure.db.repositories import HoldingsRepository
from app.infrastructure.io.ibkr_activity_statement import parse_ibkr_activity_statement


async def import_holdings_ibkr(
    source: str | Path,
    as_of_date: datetime,
    session: AsyncSession,
) -> ImportHoldingsResult:
    """Import holdings from IBKR Activity Statement and persist to database.

    Orchestrates:
    1. Parsing IBKR Activity Statement to extract holdings
    2. Converting to PositionInput list
    3. Creating snapshot with positions (assets auto-upserted)

    Note: Does not commit. Caller owns the transaction boundary.

    Args:
        source: IBKR Activity Statement CSV content as string or Path
        as_of_date: Date the holdings are valid as of
        session: Database session for transaction management

    Returns:
        ImportHoldingsResult with snapshot_id, position_count, as_of_date

    Raises:
        ValidationError: If parsing fails (empty, missing sections, invalid data)
    """
    # 1. Parse IBKR Activity Statement
    statement = parse_ibkr_activity_statement(source)

    # 2. Convert to position inputs
    positions = _convert_holdings_to_positions(statement.holdings)

    # 3. Create snapshot (handles asset upserts internally)
    repo = HoldingsRepository(session)
    snapshot = await repo.create_snapshot(as_of_date, positions)

    return ImportHoldingsResult(
        snapshot_id=snapshot.id,
        position_count=len(snapshot.positions),
        as_of_date=snapshot.as_of_date,
    )
