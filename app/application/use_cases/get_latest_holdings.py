from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import HoldingsRepository
from app.infrastructure.io.holdings_csv import HoldingRow


class LatestHoldingsResult(BaseModel):
    """Result of fetching the latest holdings snapshot."""

    snapshot_id: int
    as_of_date: datetime
    created_at: datetime
    positions: list[HoldingRow]
    position_count: int


async def get_latest_holdings(session: AsyncSession) -> LatestHoldingsResult | None:
    """Fetch the latest holdings snapshot for display.

    Returns None if no snapshots exist.

    Note: Does not commit. Caller owns transaction boundary.
    """
    repo = HoldingsRepository(session)
    snapshot = await repo.get_latest_snapshot()

    if snapshot is None:
        return None

    positions = [
        HoldingRow(
            ticker=p.asset.ticker,
            name=p.asset.name,
            qty=p.qty,
            currency=p.asset.currency,
            asset_type=p.asset.asset_type,
        )
        for p in sorted(snapshot.positions, key=lambda p: p.asset.ticker)
    ]

    return LatestHoldingsResult(
        snapshot_id=snapshot.id,
        as_of_date=snapshot.as_of_date,
        created_at=snapshot.created_at,
        positions=positions,
        position_count=len(positions),
    )
