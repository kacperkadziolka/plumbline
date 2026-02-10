from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DataMissingError
from app.infrastructure.db.models import Asset, FxDaily, HoldingsSnapshot, Position, PriceDaily


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


class PriceInput(BaseModel):
    """Input data for creating a daily price record."""

    ticker: str
    date: date
    close: Decimal
    currency: str


class PricesRepository:
    """Repository for daily price operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_assets_by_tickers(self, tickers: set[str]) -> dict[str, Asset]:
        """Batch-fetch assets by tickers. Returns {ticker: Asset} for found tickers."""
        if not tickers:
            return {}
        result = await self._session.execute(select(Asset).where(Asset.ticker.in_(tickers)))
        return {asset.ticker: asset for asset in result.scalars().all()}

    async def upsert_prices(self, prices: list[PriceInput], ticker_to_asset: dict[str, Asset]) -> int:
        """Upsert daily price rows. Returns count of rows upserted.

        Uses INSERT ... ON CONFLICT UPDATE for idempotent imports.
        Caller must validate that all tickers exist before calling this.
        """
        if not prices:
            return 0

        for price in prices:
            asset = ticker_to_asset[price.ticker]
            stmt = sqlite_insert(PriceDaily).values(
                date=price.date,
                asset_id=asset.id,
                close=price.close,
                currency=price.currency,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "asset_id"],
                set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency},
            )
            await self._session.execute(stmt)

        await self._session.flush()
        return len(prices)

    async def get_prices(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PriceDaily]:
        """Query prices for a ticker, optionally filtered by date range.

        Returns prices sorted by date ascending.
        Raises DataMissingError if ticker not found.
        """
        asset_result = await self._session.execute(select(Asset).where(Asset.ticker == ticker))
        asset = asset_result.scalar_one_or_none()
        if asset is None:
            raise DataMissingError(
                message=f"Unknown ticker: {ticker}",
                details=f"No asset with ticker '{ticker}' exists",
            )

        query = select(PriceDaily).where(PriceDaily.asset_id == asset.id)
        if start_date is not None:
            query = query.where(PriceDaily.date >= start_date)
        if end_date is not None:
            query = query.where(PriceDaily.date <= end_date)
        query = query.order_by(PriceDaily.date)

        price_result = await self._session.execute(query)
        return list(price_result.scalars().all())


class FxInput(BaseModel):
    """Input data for creating a daily FX rate record."""

    date: date
    pair: str
    rate: Decimal


class FxRepository:
    """Repository for daily FX rate operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_fx_rates(self, rates: list[FxInput]) -> int:
        """Upsert daily FX rate rows. Returns count of rows upserted.

        Uses INSERT ... ON CONFLICT UPDATE for idempotent imports.
        """
        if not rates:
            return 0

        for fx in rates:
            stmt = sqlite_insert(FxDaily).values(
                date=fx.date,
                pair=fx.pair,
                rate=fx.rate,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "pair"],
                set_={"rate": stmt.excluded.rate},
            )
            await self._session.execute(stmt)

        await self._session.flush()
        return len(rates)

    async def get_fx_rates(
        self,
        pair: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FxDaily]:
        """Query FX rates for a pair, optionally filtered by date range.

        Returns rates sorted by date ascending.
        """
        query = select(FxDaily).where(FxDaily.pair == pair)
        if start_date is not None:
            query = query.where(FxDaily.date >= start_date)
        if end_date is not None:
            query = query.where(FxDaily.date <= end_date)
        query = query.order_by(FxDaily.date)

        result = await self._session.execute(query)
        return list(result.scalars().all())
