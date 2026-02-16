import csv
import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import overload

from pydantic import BaseModel

from app.core.errors import ValidationError


class ContributionRow(BaseModel):
    """A single row from a parsed contributions CSV."""

    date: datetime.date
    amount: Decimal
    currency: str


@overload
def parse_contributions_csv(source: str) -> list[ContributionRow]: ...


@overload
def parse_contributions_csv(source: Path) -> list[ContributionRow]: ...


def parse_contributions_csv(source: str | Path) -> list[ContributionRow]:
    """Parse a contributions CSV string or file into a list of ContributionRow objects.

    The CSV must have a header row with these columns:
    - date: ISO date (YYYY-MM-DD)
    - amount: Contribution amount (must be > 0)
    - currency: 3-letter currency code (e.g., EUR, USD)

    Args:
        source: Either a CSV string or Path to a CSV file.

    Returns:
        A list of ContributionRow sorted by date for deterministic ordering.

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
    required = {"date", "amount", "currency"}
    missing_columns = required - header_columns
    if missing_columns:
        raise ValidationError(
            message=f"Missing required columns: {', '.join(sorted(missing_columns))}",
            details=f"Header has: {', '.join(sorted(header_columns))}",
        )

    rows: list[ContributionRow] = []
    for row_num, row in enumerate(reader, start=2):
        normalized_row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

        date_str = normalized_row.get("date", "")
        if not date_str:
            raise ValidationError(
                message=f"Row {row_num}: date cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            parsed_date = datetime.date.fromisoformat(date_str)
        except ValueError as e:
            raise ValidationError(
                message=f"Row {row_num}: date must be in YYYY-MM-DD format, got '{date_str}'",
                details=f"Row data: {row}",
            ) from e

        amount_str = normalized_row.get("amount", "")
        if not amount_str:
            raise ValidationError(
                message=f"Row {row_num}: amount cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            amount = Decimal(amount_str)
        except InvalidOperation as e:
            raise ValidationError(
                message=f"Row {row_num}: amount must be a valid number, got '{amount_str}'",
                details=f"Row data: {row}",
            ) from e
        if amount <= 0:
            raise ValidationError(
                message=f"Row {row_num}: amount must be greater than 0, got '{amount}'",
                details=f"Row data: {row}",
            )

        currency = normalized_row.get("currency", "")
        if not currency:
            raise ValidationError(
                message=f"Row {row_num}: currency cannot be empty",
                details=f"Row data: {row}",
            )
        currency = currency.upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError(
                message=f"Row {row_num}: currency must be a 3-letter code, got '{currency}'",
                details=f"Row data: {row}",
            )

        rows.append(ContributionRow(date=parsed_date, amount=amount, currency=currency))

    rows.sort(key=lambda r: r.date)

    return rows
