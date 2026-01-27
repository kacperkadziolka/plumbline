from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset, HoldingsSnapshot, Position


class PositionInput(BaseModel):
    """Input data for creating a position."""

    ticker: str
    qty: Decimal
    currency: str = "EUR"
    asset_type: str = "equity"
    name: str | None = None


class HoldingsRepository:
    """Repository for holdings snapshot operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_asset_by_ticker(self, ticker: str) -> Asset | None:
        """Get an asset by ticker, or None if not found."""
        result = await self._session.execute(select(Asset).where(Asset.ticker == ticker))
        return result.scalar_one_or_none()

    async def get_or_create_asset(
        self,
        ticker: str,
        currency: str = "EUR",
        asset_type: str = "equity",
        name: str | None = None,
    ) -> Asset:
        """Get existing asset by ticker or create if not found."""
        asset = await self.get_asset_by_ticker(ticker)
        if asset is not None:
            return asset

        asset = Asset(ticker=ticker, currency=currency, asset_type=asset_type, name=name)
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def create_snapshot(
        self,
        as_of_date: datetime,
        positions: list[PositionInput],
    ) -> HoldingsSnapshot:
        """Create a holdings snapshot with positions. Creates missing assets automatically."""
        # Collect unique tickers and their metadata
        ticker_to_input: dict[str, PositionInput] = {}
        for pos in positions:
            if pos.ticker not in ticker_to_input:
                ticker_to_input[pos.ticker] = pos

        # Batch fetch existing assets
        tickers = list(ticker_to_input.keys())
        if tickers:
            result = await self._session.execute(select(Asset).where(Asset.ticker.in_(tickers)))
            existing_assets = {asset.ticker: asset for asset in result.scalars().all()}
        else:
            existing_assets = {}

        # Create missing assets
        ticker_to_asset: dict[str, Asset] = dict(existing_assets)
        for ticker, pos_input in ticker_to_input.items():
            if ticker not in ticker_to_asset:
                asset = Asset(
                    ticker=ticker,
                    currency=pos_input.currency,
                    asset_type=pos_input.asset_type,
                    name=pos_input.name,
                )
                self._session.add(asset)
                ticker_to_asset[ticker] = asset

        # Flush to get asset IDs
        await self._session.flush()

        # Create snapshot
        snapshot = HoldingsSnapshot(as_of_date=as_of_date)
        self._session.add(snapshot)
        await self._session.flush()

        # Create positions
        for pos in positions:
            position = Position(
                snapshot_id=snapshot.id,
                asset_id=ticker_to_asset[pos.ticker].id,
                qty=pos.qty,
            )
            self._session.add(position)

        await self._session.flush()

        # Refresh to load relationships for return value
        await self._session.refresh(snapshot, ["positions"])
        for position in snapshot.positions:
            await self._session.refresh(position, ["asset"])

        return snapshot

    async def get_snapshot(self, snapshot_id: int) -> HoldingsSnapshot:
        """Get a holdings snapshot by ID with positions and assets loaded.

        Raises DataMissingError if not found.
        """
        result = await self._session.execute(
            select(HoldingsSnapshot)
            .where(HoldingsSnapshot.id == snapshot_id)
            .options(selectinload(HoldingsSnapshot.positions).selectinload(Position.asset))
        )
        snapshot = result.scalar_one_or_none()

        if snapshot is None:
            raise DataMissingError(
                message="Holdings snapshot not found",
                details=f"No snapshot with id={snapshot_id}",
            )

        return snapshot

    async def get_latest_snapshot(self) -> HoldingsSnapshot | None:
        """Get the most recent holdings snapshot, or None if no snapshots exist."""
        result = await self._session.execute(
            select(HoldingsSnapshot)
            .order_by(HoldingsSnapshot.as_of_date.desc())
            .limit(1)
            .options(selectinload(HoldingsSnapshot.positions).selectinload(Position.asset))
        )
        return result.scalar_one_or_none()

    async def list_snapshots(self, limit: int = 100) -> list[HoldingsSnapshot]:
        """List holdings snapshots ordered by date descending."""
        result = await self._session.execute(
            select(HoldingsSnapshot)
            .order_by(HoldingsSnapshot.as_of_date.desc())
            .limit(limit)
            .options(selectinload(HoldingsSnapshot.positions).selectinload(Position.asset))
        )
        return list(result.scalars().all())

    async def delete_snapshot(self, snapshot_id: int) -> None:
        """Delete a holdings snapshot and its positions.

        Raises DataMissingError if not found.
        """
        snapshot = await self.get_snapshot(snapshot_id)
        await self._session.delete(snapshot)
        await self._session.flush()
