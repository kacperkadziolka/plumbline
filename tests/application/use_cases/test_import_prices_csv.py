from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import ImportPricesResult, import_prices_csv
from app.core.errors import DataMissingError, ValidationError
from app.infrastructure.db.models import Asset
from app.infrastructure.db.repositories import PricesRepository

VALID_CSV = """date,ticker,close,currency
2024-01-15,AAPL,150.00,USD
2024-01-15,GOOGL,140.00,USD
"""

VALID_CSV_ONE_ROW = """date,ticker,close,currency
2024-01-15,AAPL,150.00,USD
"""

HEADER_ONLY_CSV = """date,ticker,close,currency
"""


async def test_import_prices_csv_persists_and_returns_count(session: AsyncSession) -> None:
    """Happy path: import prices for known tickers."""
    session.add(Asset(ticker="AAPL", currency="USD", asset_type="equity"))
    session.add(Asset(ticker="GOOGL", currency="USD", asset_type="equity"))
    await session.commit()

    result = await import_prices_csv(VALID_CSV, session)
    await session.commit()

    assert isinstance(result, ImportPricesResult)
    assert result.row_count == 2

    # Query back
    repo = PricesRepository(session)
    prices = await repo.get_prices("AAPL")
    assert len(prices) == 1
    assert prices[0].close == Decimal("150.00")


async def test_import_prices_csv_raises_for_unknown_tickers(session: AsyncSession) -> None:
    """Tickers not in Asset table cause DataMissingError."""
    csv = "date,ticker,close,currency\n2024-01-15,NOPE,100.00,USD\n"

    with pytest.raises(DataMissingError) as exc_info:
        await import_prices_csv(csv, session)

    assert "NOPE" in exc_info.value.message


async def test_import_prices_csv_is_idempotent(session: AsyncSession) -> None:
    """Re-importing same data updates without duplicating."""
    session.add(Asset(ticker="AAPL", currency="USD", asset_type="equity"))
    await session.commit()

    await import_prices_csv(VALID_CSV_ONE_ROW, session)
    await session.commit()

    # Re-import with updated price
    csv2 = "date,ticker,close,currency\n2024-01-15,AAPL,155.00,USD\n"
    await import_prices_csv(csv2, session)
    await session.commit()

    repo = PricesRepository(session)
    prices = await repo.get_prices("AAPL")
    assert len(prices) == 1
    assert prices[0].close == Decimal("155.00")


async def test_import_prices_csv_raises_validation_error_for_empty_csv(session: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await import_prices_csv("", session)


async def test_import_prices_csv_with_file_path(session: AsyncSession, tmp_path: Path) -> None:
    session.add(Asset(ticker="AAPL", currency="USD", asset_type="equity"))
    await session.commit()

    csv_file = tmp_path / "prices.csv"
    csv_file.write_text(VALID_CSV_ONE_ROW)

    result = await import_prices_csv(csv_file, session)
    await session.commit()

    assert result.row_count == 1


async def test_import_prices_csv_header_only(session: AsyncSession) -> None:
    """Header-only CSV returns 0 rows."""
    result = await import_prices_csv(HEADER_ONLY_CSV, session)

    assert result.row_count == 0
