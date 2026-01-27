import csv
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import overload

from pydantic import BaseModel

from app.core.errors import ValidationError


class HoldingRow(BaseModel):
    """A single row from a parsed holdings CSV."""

    ticker: str
    qty: Decimal
    currency: str
    asset_type: str
    name: str | None = None


@overload
def parse_holdings_csv(source: str) -> list[HoldingRow]: ...


@overload
def parse_holdings_csv(source: Path) -> list[HoldingRow]: ...


def parse_holdings_csv(source: str | Path) -> list[HoldingRow]:
    """Parse a holdings CSV string or file into a list of HoldingRow objects.

    The CSV must have a header row with at least these columns:
    - ticker: Asset ticker symbol (will be uppercased)
    - qty: Quantity held (must be > 0)
    - currency: Currency code (e.g., EUR, USD)
    - asset_type: Type of asset (e.g., equity, etf, bond)

    Optional columns:
    - name: Human-readable name for the asset

    Args:
        source: Either a CSV string or Path to a CSV file.

    Returns:
        A list of HoldingRow sorted by ticker (deterministic ordering).

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

    # Derive required columns from HoldingRow model
    required_columns = {name for name, field in HoldingRow.model_fields.items() if field.is_required()}

    header_columns = {col.strip().lower() for col in reader.fieldnames}
    missing_columns = required_columns - header_columns
    if missing_columns:
        raise ValidationError(
            message=f"Missing required columns: {', '.join(sorted(missing_columns))}",
            details=f"Header has: {', '.join(sorted(header_columns))}",
        )

    rows: list[HoldingRow] = []
    for row_num, row in enumerate(reader, start=2):  # Header is row 1
        normalized_row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

        ticker = normalized_row.get("ticker", "")
        if not ticker:
            raise ValidationError(
                message=f"Row {row_num}: ticker cannot be empty",
                details=f"Row data: {row}",
            )
        ticker = ticker.upper()

        qty_str = normalized_row.get("qty", "")
        if not qty_str:
            raise ValidationError(
                message=f"Row {row_num}: qty cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            qty = Decimal(qty_str)
        except InvalidOperation as e:
            raise ValidationError(
                message=f"Row {row_num}: qty must be a valid number, got '{qty_str}'",
                details=f"Row data: {row}",
            ) from e
        if qty <= 0:
            raise ValidationError(
                message=f"Row {row_num}: qty must be greater than 0, got '{qty}'",
                details=f"Row data: {row}",
            )

        currency = normalized_row.get("currency", "")
        if not currency:
            raise ValidationError(
                message=f"Row {row_num}: currency cannot be empty",
                details=f"Row data: {row}",
            )

        asset_type = normalized_row.get("asset_type", "")
        if not asset_type:
            raise ValidationError(
                message=f"Row {row_num}: asset_type cannot be empty",
                details=f"Row data: {row}",
            )

        name = normalized_row.get("name") or None

        rows.append(
            HoldingRow(
                ticker=ticker,
                qty=qty,
                currency=currency,
                asset_type=asset_type,
                name=name,
            )
        )

    rows.sort(key=lambda r: r.ticker)

    return rows
