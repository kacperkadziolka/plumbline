import csv
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import overload

from pydantic import BaseModel

from app.core.errors import ValidationError
from app.infrastructure.io.holdings_csv import HoldingRow


class AssetInfo(BaseModel):
    """Asset metadata from Financial Instrument Information section."""

    name: str
    asset_type: str  # "equity" or "etf"


class IBKRActivityStatement(BaseModel):
    """Parsed IBKR Activity Statement."""

    holdings: list[HoldingRow]
    statement_period: str | None = None


def _map_ibkr_type_to_asset_type(ibkr_type: str) -> str:
    """Map IBKR instrument type to our asset_type."""
    ibkr_type_upper = ibkr_type.upper()
    if ibkr_type_upper == "ETF":
        return "etf"
    # COMMON, PREFERRED, ADR, etc. → equity
    return "equity"


def _parse_financial_instrument_info(rows: list[list[str]]) -> dict[str, AssetInfo]:
    """Parse Financial Instrument Information section into symbol → AssetInfo lookup.

    Expected row format (by index):
    [0] Section name: "Financial Instrument Information"
    [1] Row type: "Header" or "Data"
    [2] Asset Category: e.g., "Stocks"
    [3] Symbol: e.g., "AMZN"
    [4] Description: e.g., "AMAZON.COM INC"
    ...
    [9] Type: e.g., "COMMON" or "ETF"
    """
    result: dict[str, AssetInfo] = {}

    for row in rows:
        if len(row) < 10:
            continue
        if row[1] != "Data":
            continue

        symbol = row[3].strip().upper()
        description = row[4].strip()
        instrument_type = row[9].strip() if len(row) > 9 else ""

        if symbol:
            result[symbol] = AssetInfo(
                name=description or symbol,
                asset_type=_map_ibkr_type_to_asset_type(instrument_type),
            )

    return result


def _parse_open_positions(
    rows: list[list[str]],
    asset_lookup: dict[str, AssetInfo],
) -> list[HoldingRow]:
    """Parse Open Positions section into HoldingRow list.

    Expected row format (by index):
    [0] Section name: "Open Positions"
    [1] Row type: "Header", "Data", or "Total"
    [2] DataDiscriminator: "Summary" for actual positions
    [3] Asset Category: e.g., "Stocks"
    [4] Currency: e.g., "USD"
    [5] Symbol: e.g., "AMZN"
    [6] Quantity: e.g., "10.5041"
    """
    holdings: list[HoldingRow] = []

    for row in rows:
        if len(row) < 7:
            continue
        # Only process Data rows with Summary discriminator
        if row[1] != "Data" or row[2] != "Summary":
            continue

        symbol = row[5].strip().upper()
        if not symbol:
            continue

        currency = row[4].strip().upper()
        qty_str = row[6].strip()

        try:
            qty = Decimal(qty_str)
        except InvalidOperation as e:
            raise ValidationError(
                message=f"Invalid quantity for {symbol}: '{qty_str}'",
                details="Quantity must be a valid number",
            ) from e

        if qty <= 0:
            raise ValidationError(
                message=f"Invalid quantity for {symbol}: {qty}",
                details="Quantity must be greater than 0",
            )

        # Look up asset info, with fallback defaults
        asset_info = asset_lookup.get(symbol)
        if asset_info:
            name = asset_info.name
            asset_type = asset_info.asset_type
        else:
            name = symbol
            asset_type = "equity"

        holdings.append(
            HoldingRow(
                ticker=symbol,
                qty=qty,
                currency=currency,
                asset_type=asset_type,
                name=name,
            )
        )

    return holdings


def _parse_statement_period(rows: list[list[str]]) -> str | None:
    """Extract statement period from Statement section.

    Looks for row: ["Statement", "Data", "Period", "January 1, 2026 - January 31, 2026"]
    """
    for row in rows:
        if len(row) >= 4 and row[1] == "Data" and row[2] == "Period":
            return row[3].strip()
    return None


def _group_rows_by_section(reader: Iterator[list[str]]) -> dict[str, list[list[str]]]:
    """Group CSV rows by their section (first column)."""
    sections: dict[str, list[list[str]]] = {}

    for row in reader:
        if not row:
            continue
        section_name = row[0].strip()
        if section_name:
            if section_name not in sections:
                sections[section_name] = []
            sections[section_name].append(row)

    return sections


@overload
def parse_ibkr_activity_statement(source: str) -> IBKRActivityStatement: ...


@overload
def parse_ibkr_activity_statement(source: Path) -> IBKRActivityStatement: ...


def parse_ibkr_activity_statement(source: str | Path) -> IBKRActivityStatement:
    """Parse IBKR Activity Statement CSV and extract holdings.

    The IBKR Activity Statement is a multi-section CSV where each section
    has different column structures. This parser extracts:
    - Open Positions (Summary rows) for holdings data
    - Financial Instrument Information for asset names and types
    - Statement period metadata

    Args:
        source: Either CSV content as string or Path to CSV file.

    Returns:
        IBKRActivityStatement with holdings list and optional period.

    Raises:
        ValidationError: If file is empty, malformed, or contains invalid data.
    """
    if isinstance(source, Path):
        text = source.read_text()
    else:
        text = source

    stripped = text.strip()
    if not stripped:
        raise ValidationError(
            message="IBKR Activity Statement is empty",
            details="Input contains no data or only whitespace",
        )

    reader = csv.reader(StringIO(stripped))
    sections = _group_rows_by_section(reader)

    if "Open Positions" not in sections:
        raise ValidationError(
            message="No Open Positions section found",
            details="IBKR Activity Statement must contain an 'Open Positions' section",
        )

    # Parse Financial Instrument Information first for asset type lookup
    asset_lookup: dict[str, AssetInfo] = {}
    if "Financial Instrument Information" in sections:
        asset_lookup = _parse_financial_instrument_info(sections["Financial Instrument Information"])

    # Parse Open Positions
    holdings = _parse_open_positions(sections["Open Positions"], asset_lookup)

    if not holdings:
        raise ValidationError(
            message="No holdings found in Open Positions",
            details="The Open Positions section contains no Summary rows with valid data",
        )

    # Sort by ticker for deterministic ordering
    holdings.sort(key=lambda h: h.ticker)

    # Extract statement period
    statement_period = None
    if "Statement" in sections:
        statement_period = _parse_statement_period(sections["Statement"])

    return IBKRActivityStatement(
        holdings=holdings,
        statement_period=statement_period,
    )
