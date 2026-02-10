from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.repositories import PriceInput, PricesRepository
from app.infrastructure.io.prices_csv import PriceRow, parse_prices_csv


class ImportPricesResult(BaseModel):
    """Result of importing daily prices from CSV."""

    row_count: int


def _convert_prices(rows: list[PriceRow]) -> list[PriceInput]:
    """Convert PriceRow list to PriceInput list."""
    return [
        PriceInput(
            ticker=r.ticker,
            date=r.date,
            close=r.close,
            currency=r.currency,
        )
        for r in rows
    ]


async def import_prices_csv(
    source: str | Path,
    session: AsyncSession,
) -> ImportPricesResult:
    """Import daily prices from CSV and persist to database.

    Orchestrates:
    1. Parsing CSV to PriceRow list
    2. Validating all tickers exist in the Asset table
    3. Converting to PriceInput list
    4. Upserting prices (ON CONFLICT UPDATE for idempotent re-imports)

    Note: Does not commit. Caller owns the transaction boundary.

    Args:
        source: CSV content as string or Path to CSV file
        session: Database session for transaction management

    Returns:
        ImportPricesResult with row_count

    Raises:
        ValidationError: If CSV parsing fails (empty, missing columns, invalid data)
        DataMissingError: If any tickers in CSV are not found in Asset table
    """
    # 1. Parse CSV (raises ValidationError on invalid input)
    rows = parse_prices_csv(source)

    if not rows:
        return ImportPricesResult(row_count=0)

    # 2. Validate tickers exist
    repo = PricesRepository(session)
    unique_tickers = {row.ticker for row in rows}
    ticker_to_asset = await repo.get_assets_by_tickers(unique_tickers)

    missing_tickers = unique_tickers - set(ticker_to_asset.keys())
    if missing_tickers:
        raise DataMissingError(
            message=f"Unknown tickers: {', '.join(sorted(missing_tickers))}",
            details="All tickers must exist in the Asset table before importing prices. "
            "Import holdings first to auto-create assets.",
        )

    # 3. Convert to price inputs
    prices = _convert_prices(rows)

    # 4. Upsert prices
    count = await repo.upsert_prices(prices, ticker_to_asset)

    return ImportPricesResult(row_count=count)
