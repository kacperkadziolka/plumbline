from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.domain.valuation import (
    BASE_CURRENCY,
    PortfolioValuation,
    compute_currency_exposures,
    compute_weights,
    valuate_portfolio,
)
from app.domain.valuation import PositionInput as DomainPositionInput
from app.infrastructure.db.repositories import (
    FxRepository,
    HoldingsRepository,
    PricesRepository,
)


class ValuationPositionRow(BaseModel):
    ticker: str
    name: str | None
    currency: str
    qty: Decimal
    price: Decimal
    fx_rate: Decimal
    value_local: Decimal
    value_base: Decimal
    weight: Decimal


class CurrencyExposureRow(BaseModel):
    currency: str
    value_base: Decimal
    weight: Decimal


class ValuationResult(BaseModel):
    snapshot_id: int
    as_of_date: date
    base_currency: str
    positions: list[ValuationPositionRow]
    total_value: Decimal
    currency_exposures: list[CurrencyExposureRow]


async def get_domain_valuation(
    as_of_date: date,
    session: AsyncSession,
) -> PortfolioValuation:
    """Fetch holdings, prices, and FX rates, then compute the domain PortfolioValuation.

    Raises:
        DataMissingError: If no snapshot exists, or if prices/FX rates are missing.
    """
    holdings_repo = HoldingsRepository(session)
    snapshot = await holdings_repo.get_latest_snapshot()
    if snapshot is None:
        raise DataMissingError(
            message="No holdings snapshot found",
            details="Import holdings before running valuation",
        )

    domain_positions: list[DomainPositionInput] = []
    asset_ids: set[int] = set()
    currencies_needed: set[str] = set()

    for pos in snapshot.positions:
        domain_positions.append(
            DomainPositionInput(
                ticker=pos.asset.ticker,
                currency=pos.asset.currency,
                qty=pos.qty,
            )
        )
        asset_ids.add(pos.asset_id)
        if pos.asset.currency != BASE_CURRENCY:
            currencies_needed.add(pos.asset.currency)

    prices_repo = PricesRepository(session)
    price_rows = await prices_repo.get_prices_for_date(asset_ids, as_of_date)
    prices_by_ticker: dict[str, Decimal] = {}
    for pos in snapshot.positions:
        if pos.asset_id in price_rows:
            prices_by_ticker[pos.asset.ticker] = price_rows[pos.asset_id].close

    fx_repo = FxRepository(session)
    fx_pairs = {f"{cur}/{BASE_CURRENCY}" for cur in currencies_needed}
    fx_rows = await fx_repo.get_fx_rates_for_date(fx_pairs, as_of_date)
    fx_by_pair: dict[str, Decimal] = {pair: row.rate for pair, row in fx_rows.items()}

    return valuate_portfolio(
        as_of_date=as_of_date,
        positions=domain_positions,
        prices=prices_by_ticker,
        fx_rates=fx_by_pair,
    )


async def valuate_portfolio_for_date(
    as_of_date: date,
    session: AsyncSession,
) -> ValuationResult:
    """Compute portfolio valuation for a specific date.

    Note: Does not commit. Caller owns transaction boundary.

    Raises:
        DataMissingError: If no snapshot exists, or if prices/FX rates are missing.
    """
    holdings_repo = HoldingsRepository(session)
    snapshot = await holdings_repo.get_latest_snapshot()
    if snapshot is None:
        raise DataMissingError(
            message="No holdings snapshot found",
            details="Import holdings before running valuation",
        )

    ticker_to_name: dict[str, str | None] = {}
    for pos in snapshot.positions:
        ticker_to_name[pos.asset.ticker] = pos.asset.name

    valuation = await get_domain_valuation(as_of_date, session)

    weights = compute_weights(valuation)
    display_positions = [
        ValuationPositionRow(
            ticker=pv.ticker,
            name=ticker_to_name.get(pv.ticker),
            currency=pv.currency,
            qty=pv.qty,
            price=pv.price,
            fx_rate=pv.fx_rate,
            value_local=pv.value_local,
            value_base=pv.value_base,
            weight=w,
        )
        for pv, w in zip(valuation.positions, weights, strict=True)
    ]

    exposures = compute_currency_exposures(valuation)
    exposure_rows = [
        CurrencyExposureRow(currency=exp.currency, value_base=exp.value_base, weight=exp.weight) for exp in exposures
    ]

    return ValuationResult(
        snapshot_id=snapshot.id,
        as_of_date=valuation.as_of_date,
        base_currency=valuation.base_currency,
        positions=display_positions,
        total_value=valuation.total_value,
        currency_exposures=exposure_rows,
    )
