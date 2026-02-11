from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.errors import DataMissingError

BASE_CURRENCY = "EUR"


@dataclass(frozen=True)
class PositionInput:
    ticker: str
    currency: str
    qty: Decimal


@dataclass(frozen=True)
class PositionValuation:
    ticker: str
    currency: str
    qty: Decimal
    price: Decimal
    fx_rate: Decimal
    value_local: Decimal
    value_base: Decimal


@dataclass(frozen=True)
class PortfolioValuation:
    as_of_date: date
    base_currency: str
    positions: list[PositionValuation]
    total_value: Decimal


def valuate_portfolio(
    as_of_date: date,
    positions: list[PositionInput],
    prices: dict[str, Decimal],
    fx_rates: dict[str, Decimal],
) -> PortfolioValuation:
    """Compute portfolio valuation from positions, prices, and FX rates.

    All inputs are plain data. This function is pure and deterministic.
    Collects ALL missing data points before raising so the user sees everything at once.

    Raises:
        DataMissingError: If any required price or FX rate is missing.
    """
    missing: list[str] = []
    needed_fx_pairs: set[str] = set()

    for pos in sorted(positions, key=lambda p: p.ticker):
        if pos.ticker not in prices:
            missing.append(f"Missing price for {pos.ticker} on {as_of_date}")
        if pos.currency != BASE_CURRENCY:
            pair = f"{pos.currency}/{BASE_CURRENCY}"
            needed_fx_pairs.add(pair)

    for pair in sorted(needed_fx_pairs):
        if pair not in fx_rates:
            missing.append(f"Missing FX rate for {pair} on {as_of_date}")

    if missing:
        raise DataMissingError(
            message=f"Missing market data for valuation on {as_of_date}",
            details="; ".join(missing),
        )

    valuations: list[PositionValuation] = []
    for pos in sorted(positions, key=lambda p: p.ticker):
        price = prices[pos.ticker]
        if pos.currency == BASE_CURRENCY:
            fx_rate = Decimal("1")
        else:
            pair = f"{pos.currency}/{BASE_CURRENCY}"
            fx_rate = fx_rates[pair]

        value_local = pos.qty * price
        value_base = value_local * fx_rate

        valuations.append(
            PositionValuation(
                ticker=pos.ticker,
                currency=pos.currency,
                qty=pos.qty,
                price=price,
                fx_rate=fx_rate,
                value_local=value_local,
                value_base=value_base,
            )
        )

    total = sum((v.value_base for v in valuations), Decimal("0"))

    return PortfolioValuation(
        as_of_date=as_of_date,
        base_currency=BASE_CURRENCY,
        positions=valuations,
        total_value=total,
    )


@dataclass(frozen=True)
class CurrencyExposure:
    currency: str
    value_base: Decimal
    weight: Decimal


def compute_weights(valuation: PortfolioValuation) -> list[Decimal]:
    if not valuation.positions or valuation.total_value == Decimal("0"):
        return [Decimal("0")] * len(valuation.positions)
    return [pos.value_base / valuation.total_value for pos in valuation.positions]


def compute_currency_exposures(valuation: PortfolioValuation) -> list[CurrencyExposure]:
    if not valuation.positions:
        return []

    totals_by_ccy: dict[str, Decimal] = {}
    for pos in valuation.positions:
        totals_by_ccy[pos.currency] = totals_by_ccy.get(pos.currency, Decimal("0")) + pos.value_base

    if valuation.total_value == Decimal("0"):
        return [
            CurrencyExposure(currency=ccy, value_base=val, weight=Decimal("0"))
            for ccy, val in sorted(totals_by_ccy.items())
        ]

    return [
        CurrencyExposure(currency=ccy, value_base=val, weight=val / valuation.total_value)
        for ccy, val in sorted(totals_by_ccy.items())
    ]
