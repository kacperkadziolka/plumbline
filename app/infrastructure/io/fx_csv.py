import csv
import datetime
import re
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import overload

from pydantic import BaseModel

from app.core.errors import ValidationError

_PAIR_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")


class FxRow(BaseModel):
    """A single row from a parsed FX rates CSV."""

    date: datetime.date
    pair: str
    rate: Decimal


@overload
def parse_fx_csv(source: str) -> list[FxRow]: ...


@overload
def parse_fx_csv(source: Path) -> list[FxRow]: ...


def parse_fx_csv(source: str | Path) -> list[FxRow]:
    """Parse an FX rates CSV string or file into a list of FxRow objects.

    The CSV must have a header row with these columns:
    - date: ISO date (YYYY-MM-DD)
    - pair: Currency pair in XXX/YYY format (e.g., USD/EUR)
    - rate: Exchange rate (must be > 0)

    Args:
        source: Either a CSV string or Path to a CSV file.

    Returns:
        A list of FxRow sorted by (date, pair) for deterministic ordering.

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
    required = {"date", "pair", "rate"}
    missing_columns = required - header_columns
    if missing_columns:
        raise ValidationError(
            message=f"Missing required columns: {', '.join(sorted(missing_columns))}",
            details=f"Header has: {', '.join(sorted(header_columns))}",
        )

    rows: list[FxRow] = []
    for row_num, row in enumerate(reader, start=2):
        normalized_row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

        date_str = normalized_row.get("date", "")
        if not date_str:
            raise ValidationError(
                message=f"Row {row_num}: date cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError as e:
            raise ValidationError(
                message=f"Row {row_num}: date must be in YYYY-MM-DD format, got '{date_str}'",
                details=f"Row data: {row}",
            ) from e

        pair = normalized_row.get("pair", "")
        if not pair:
            raise ValidationError(
                message=f"Row {row_num}: pair cannot be empty",
                details=f"Row data: {row}",
            )
        pair = pair.upper()
        if not _PAIR_RE.match(pair):
            raise ValidationError(
                message=f"Row {row_num}: pair must be in format XXX/YYY (e.g., USD/EUR), got '{pair}'",
                details=f"Row data: {row}",
            )

        rate_str = normalized_row.get("rate", "")
        if not rate_str:
            raise ValidationError(
                message=f"Row {row_num}: rate cannot be empty",
                details=f"Row data: {row}",
            )
        try:
            rate = Decimal(rate_str)
        except InvalidOperation as e:
            raise ValidationError(
                message=f"Row {row_num}: rate must be a valid number, got '{rate_str}'",
                details=f"Row data: {row}",
            ) from e
        if rate <= 0:
            raise ValidationError(
                message=f"Row {row_num}: rate must be greater than 0, got '{rate}'",
                details=f"Row data: {row}",
            )

        rows.append(FxRow(date=date, pair=pair, rate=rate))

    rows.sort(key=lambda r: (r.date, r.pair))

    return rows
