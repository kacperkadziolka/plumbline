import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import overload

from pydantic import BaseModel

from app.core.errors import ValidationError


class PriceRow(BaseModel):
    """A single row from a parsed prices CSV."""

    date: date
    ticker: str
    close: Decimal
    currency: str

    @classmethod
    def required_columns(cls) -> set[str]:
        """Return the set of required column names for CSV parsing."""
        return {name for name, field in cls.model_fields.items() if field.is_required()}


@overload
def parse_prices_csv(source: str) -> list[PriceRow]: ...


@overload
def parse_prices_csv(source: Path) -> list[PriceRow]: ...


def parse_prices_csv(source: str | Path) -> list[PriceRow]:
    """Parse a prices CSV string or file into a list of PriceRow objects.

    The CSV must have a header row with these columns:
    - date: Date in YYYY-MM-DD format
    - ticker: Asset ticker symbol (will be uppercased)
    - close: Closing price (must be > 0)
    - currency: Currency code (e.g., EUR, USD)

    Args:
        source: Either a CSV string or Path to a CSV file.

    Returns:
        A list of PriceRow sorted by (date, ticker) for deterministic ordering.

    Raises:
        ValidationError: If CSV is empty, missing required columns, or contains invalid data.
    """
    if isinstance(source, Path):
        text = source.read_text()
    else:
        text = source

    stripped = text.strip()
    if not stripped:
        raise ValidationError(
            message="CSV is empty",
            details="Input contains no data or only whitespace",
        )

    reader = csv.DictReader(StringIO(stripped))

    if reader.fieldnames is None:
        raise ValidationError(
            message="CSV is empty",
            details="No header row found",
        )

    header_columns = {col.strip().lower() for col in reader.fieldnames}
    missing_columns = PriceRow.required_columns() - header_columns
    if missing_columns:
        raise ValidationError(
            message=f"Missing required columns: {', '.join(sorted(missing_columns))}",
            details=f"Header has: {', '.join(sorted(header_columns))}",
        )

    rows: list[PriceRow] = []
    for row_num, row in enumerate(reader, start=2):  # Header is row 1
        normalized_row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

        date_str = normalized_row.get("date", "")
        if not date_str:
            raise ValidationError(
                message=f"Row {row_num}: date cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            parsed_date = date.fromisoformat(date_str)
        except ValueError as e:
            raise ValidationError(
                message=f"Row {row_num}: date must be in YYYY-MM-DD format, got '{date_str}'",
                details=f"Row data: {row}",
            ) from e

        ticker = normalized_row.get("ticker", "")
        if not ticker:
            raise ValidationError(
                message=f"Row {row_num}: ticker cannot be empty",
                details=f"Row data: {row}",
            )
        ticker = ticker.upper()

        close_str = normalized_row.get("close", "")
        if not close_str:
            raise ValidationError(
                message=f"Row {row_num}: close cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            close = Decimal(close_str)
        except InvalidOperation as e:
            raise ValidationError(
                message=f"Row {row_num}: close must be a valid number, got '{close_str}'",
                details=f"Row data: {row}",
            ) from e
        if close <= 0:
            raise ValidationError(
                message=f"Row {row_num}: close must be greater than 0, got '{close}'",
                details=f"Row data: {row}",
            )

        currency = normalized_row.get("currency", "")
        if not currency:
            raise ValidationError(
                message=f"Row {row_num}: currency cannot be empty",
                details=f"Row data: {row}",
            )

        rows.append(
            PriceRow(
                date=parsed_date,
                ticker=ticker,
                close=close,
                currency=currency,
            )
        )

    rows.sort(key=lambda r: (r.date, r.ticker))

    return rows
