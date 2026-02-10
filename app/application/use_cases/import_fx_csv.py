from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import FxInput, FxRepository
from app.infrastructure.io.fx_csv import FxRow, parse_fx_csv


class ImportFxResult(BaseModel):
    """Result of importing daily FX rates from CSV."""

    row_count: int


def _convert_fx_rates(rows: list[FxRow]) -> list[FxInput]:
    """Convert FxRow list to FxInput list."""
    return [
        FxInput(
            date=r.date,
            pair=r.pair,
            rate=r.rate,
        )
        for r in rows
    ]


async def import_fx_csv(
    source: str | Path,
    session: AsyncSession,
) -> ImportFxResult:
    """Import daily FX rates from CSV and persist to database.

    Orchestrates:
    1. Parsing CSV to FxRow list
    2. Converting to FxInput list
    3. Upserting FX rates (ON CONFLICT UPDATE for idempotent re-imports)

    Note: Does not commit. Caller owns the transaction boundary.

    Args:
        source: CSV content as string or Path to CSV file
        session: Database session for transaction management

    Returns:
        ImportFxResult with row_count

    Raises:
        ValidationError: If CSV parsing fails (empty, missing columns, invalid data)
    """
    # 1. Parse CSV (raises ValidationError on invalid input)
    rows = parse_fx_csv(source)

    if not rows:
        return ImportFxResult(row_count=0)

    # 2. Convert to FX inputs
    rates = _convert_fx_rates(rows)

    # 3. Upsert FX rates
    repo = FxRepository(session)
    count = await repo.upsert_fx_rates(rates)

    return ImportFxResult(row_count=count)
