from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import ImportFxResult, import_fx_csv
from app.core.errors import ValidationError
from app.infrastructure.db.repositories import FxRepository

VALID_CSV = """date,pair,rate
2024-01-15,USD/EUR,0.92
2024-01-15,GBP/EUR,1.16
"""

VALID_CSV_ONE_ROW = """date,pair,rate
2024-01-15,USD/EUR,0.92
"""

HEADER_ONLY_CSV = """date,pair,rate
"""


async def test_import_fx_csv_persists_and_returns_count(session: AsyncSession) -> None:
    """Happy path: import FX rates."""
    result = await import_fx_csv(VALID_CSV, session)
    await session.commit()

    assert isinstance(result, ImportFxResult)
    assert result.row_count == 2

    # Query back
    repo = FxRepository(session)
    rates = await repo.get_fx_rates("USD/EUR")
    assert len(rates) == 1
    assert rates[0].rate == Decimal("0.92")


async def test_import_fx_csv_is_idempotent(session: AsyncSession) -> None:
    """Re-importing same data updates without duplicating."""
    await import_fx_csv(VALID_CSV_ONE_ROW, session)
    await session.commit()

    # Re-import with updated rate
    csv2 = "date,pair,rate\n2024-01-15,USD/EUR,0.93\n"
    await import_fx_csv(csv2, session)
    await session.commit()

    repo = FxRepository(session)
    rates = await repo.get_fx_rates("USD/EUR")
    assert len(rates) == 1
    assert rates[0].rate == Decimal("0.93")


async def test_import_fx_csv_raises_validation_error_for_empty_csv(session: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await import_fx_csv("", session)


async def test_import_fx_csv_with_file_path(session: AsyncSession, tmp_path: Path) -> None:
    csv_file = tmp_path / "fx.csv"
    csv_file.write_text(VALID_CSV_ONE_ROW)

    result = await import_fx_csv(csv_file, session)
    await session.commit()

    assert result.row_count == 1


async def test_import_fx_csv_header_only(session: AsyncSession) -> None:
    """Header-only CSV returns 0 rows."""
    result = await import_fx_csv(HEADER_ONLY_CSV, session)

    assert result.row_count == 0
