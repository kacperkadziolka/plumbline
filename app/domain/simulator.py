import hashlib
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.errors import DataMissingError, ValidationError
from app.domain.allocator import AllocationResult, TradeProposal, allocate_contribution
from app.domain.policy import PolicyConfig
from app.domain.valuation import PortfolioValuation, PositionInput, valuate_portfolio

_BPS_DIVISOR = Decimal("10000")


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TickerInfo:
    ticker: str
    currency: str


@dataclass(frozen=True)
class ScheduledContribution:
    date: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class SimulationInput:
    policy: PolicyConfig
    schedule: list[ScheduledContribution]
    prices: dict[date, dict[str, Decimal]]
    fx_rates: dict[date, dict[str, Decimal]]
    ticker_info: dict[str, TickerInfo]
    include_satellite: bool


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquityCurveRow:
    date: date
    equity: Decimal
    cash: Decimal
    positions_value: Decimal
    drawdown: Decimal
    cumulative_costs: Decimal
    contribution_today: Decimal
    cumulative_traded_value: Decimal


@dataclass(frozen=True)
class SimulationMetrics:
    total_return: Decimal
    cagr: Decimal | None
    max_drawdown: Decimal
    total_costs: Decimal
    total_contributions: Decimal
    final_equity: Decimal
    annualized_volatility: Decimal | None
    turnover: Decimal


@dataclass(frozen=True)
class SimulationResult:
    curve: list[EquityCurveRow]
    metrics: SimulationMetrics
    curve_hash: str
    policy_hash: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_input(sim_input: SimulationInput) -> None:
    if not sim_input.schedule:
        raise ValidationError(message="Contribution schedule must not be empty")

    base_ccy = sim_input.policy.base_currency
    for entry in sim_input.schedule:
        if entry.currency.upper() != base_ccy:
            raise ValidationError(
                message=f"Schedule currency '{entry.currency}' does not match policy base currency '{base_ccy}'"
            )
        if entry.amount <= Decimal("0"):
            raise ValidationError(
                message="Scheduled contribution amount must be positive", details=f"Got {entry.amount}"
            )

    # Collect all tickers referenced by the policy
    policy_tickers: set[str] = set(sim_input.policy.buckets.core.targets.keys())
    if sim_input.include_satellite and sim_input.policy.buckets.satellite is not None:
        policy_tickers |= set(sim_input.policy.buckets.satellite.targets.keys())

    missing_info = sorted(policy_tickers - set(sim_input.ticker_info.keys()))
    if missing_info:
        raise ValidationError(
            message="Missing ticker_info for policy tickers",
            details=", ".join(missing_info),
        )

    available_dates = set(sim_input.prices.keys())
    missing_dates = sorted(d for entry in sim_input.schedule if (d := entry.date) not in available_dates)
    if missing_dates:
        raise DataMissingError(
            message="Missing price data for scheduled contribution dates",
            details=", ".join(d.isoformat() for d in missing_dates),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_position_inputs(
    holdings: dict[str, Decimal],
    ticker_info: dict[str, TickerInfo],
) -> list[PositionInput]:
    return [
        PositionInput(ticker=ticker, currency=ticker_info[ticker].currency, qty=qty)
        for ticker, qty in sorted(holdings.items())
        if qty > Decimal("0")
    ]


def _execute_trades(
    trades: list[TradeProposal],
    holdings: dict[str, Decimal],
    day_prices: dict[str, Decimal],
    day_fx: dict[str, Decimal],
    ticker_info: dict[str, TickerInfo],
    policy: PolicyConfig,
) -> Decimal:
    """Execute trades by updating holdings in-place. Returns total costs incurred."""
    total_costs = Decimal("0")

    for trade in trades:
        # Commission per trade
        commission = policy.costs.commission_fixed
        total_costs += commission

        ticker_ccy = ticker_info[trade.ticker].currency
        buy_base = trade.buy_amount

        if ticker_ccy == policy.base_currency:
            local_amount = buy_base
        else:
            pair = f"{ticker_ccy}/{policy.base_currency}"
            fx_rate = day_fx.get(pair)
            if fx_rate is None:
                raise DataMissingError(
                    message=f"Missing FX rate for {pair} during trade execution",
                )
            # buy_base EUR, rate = 1 FCY = fx_rate EUR  →  local = buy_base / fx_rate
            local_amount_mid = buy_base / fx_rate
            spread_factor = Decimal("1") - Decimal(policy.costs.fx_spread_bps) / _BPS_DIVISOR
            local_amount = local_amount_mid * spread_factor
            # FX spread cost in base currency
            fx_cost = (local_amount_mid - local_amount) * fx_rate
            total_costs += fx_cost

        price = day_prices[trade.ticker]
        shares_bought = local_amount / price
        holdings[trade.ticker] = holdings.get(trade.ticker, Decimal("0")) + shares_bought

    return total_costs


def _compute_annualized_volatility(curve: list[EquityCurveRow]) -> Decimal | None:
    """Annualized volatility from TWR-adjusted daily returns.

    Adjusts for contributions: return_i = (equity_i - contribution_i - equity_{i-1}) / equity_{i-1}.
    Returns None if fewer than 2 return observations.
    """
    daily_returns: list[Decimal] = []
    for i in range(1, len(curve)):
        prev_equity = curve[i - 1].equity
        if prev_equity <= Decimal("0"):
            continue
        adjusted_equity = curve[i].equity - curve[i].contribution_today
        daily_returns.append((adjusted_equity - prev_equity) / prev_equity)

    if len(daily_returns) < 2:
        return None

    n = len(daily_returns)
    mean = sum(daily_returns, Decimal("0")) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    # Float conversion only for sqrt (documented MVP simplification, same as CAGR)
    stdev = Decimal(str(math.sqrt(float(variance))))
    return stdev * Decimal(str(math.sqrt(252)))


def _compute_turnover(curve: list[EquityCurveRow]) -> Decimal:
    """Turnover = total traded value / average portfolio equity."""
    total_traded = curve[-1].cumulative_traded_value
    if total_traded == Decimal("0"):
        return Decimal("0")

    positive_equities = [row.equity for row in curve if row.equity > Decimal("0")]
    if not positive_equities:
        return Decimal("0")

    avg_equity = sum(positive_equities, Decimal("0")) / len(positive_equities)
    return total_traded / avg_equity


def _compute_metrics(curve: list[EquityCurveRow]) -> SimulationMetrics:
    total_contributions = sum((row.contribution_today for row in curve), Decimal("0"))
    final_equity = curve[-1].equity
    total_costs = curve[-1].cumulative_costs
    max_drawdown = max((row.drawdown for row in curve), default=Decimal("0"))

    if total_contributions > Decimal("0"):
        total_return = (final_equity - total_contributions) / total_contributions
    else:
        total_return = Decimal("0")

    # CAGR: simple approximation using float exponentiation (documented MVP simplification)
    cagr: Decimal | None = None
    days = (curve[-1].date - curve[0].date).days
    if days >= 365 and total_contributions > Decimal("0") and final_equity > Decimal("0"):
        ratio = float(final_equity / total_contributions)
        exponent = 365.0 / float(days)
        cagr = Decimal(str(round(ratio**exponent - 1.0, 10)))

    return SimulationMetrics(
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_drawdown,
        total_costs=total_costs,
        total_contributions=total_contributions,
        final_equity=final_equity,
        annualized_volatility=_compute_annualized_volatility(curve),
        turnover=_compute_turnover(curve),
    )


def _compute_curve_hash(curve: list[EquityCurveRow]) -> str:
    parts: list[str] = []
    for row in curve:
        parts.append(
            f"{row.date.isoformat()}|{row.equity}|{row.cash}|"
            f"{row.positions_value}|{row.drawdown}|"
            f"{row.cumulative_costs}|{row.contribution_today}|"
            f"{row.cumulative_traded_value}"
        )
    serialized = "\n".join(parts)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_simulation(sim_input: SimulationInput) -> SimulationResult:
    """Run a deterministic daily simulation over historical data.

    Iterates over every date present in prices (sorted), applies scheduled
    contributions via the allocator, tracks positions/cash/costs, and
    produces an equity curve with summary metrics.

    Raises:
        ValidationError: Invalid inputs.
        DataMissingError: Missing price or FX data.
    """
    _validate_input(sim_input)

    policy = sim_input.policy
    ticker_info = sim_input.ticker_info
    dates = sorted(sim_input.prices.keys())

    schedule_map: dict[date, Decimal] = {}
    for entry in sim_input.schedule:
        schedule_map[entry.date] = schedule_map.get(entry.date, Decimal("0")) + entry.amount

    # Mutable simulation state
    holdings: dict[str, Decimal] = {}
    cash = Decimal("0")
    cumulative_costs = Decimal("0")
    cumulative_traded_value = Decimal("0")
    peak_equity = Decimal("0")

    curve: list[EquityCurveRow] = []

    for day_date in dates:
        day_prices = sim_input.prices[day_date]
        day_fx = sim_input.fx_rates.get(day_date, {})

        # --- Mark-to-market ---
        position_inputs = _build_position_inputs(holdings, ticker_info)
        if position_inputs:
            valuation = valuate_portfolio(day_date, position_inputs, day_prices, day_fx)
            positions_value = valuation.total_value
        else:
            valuation = PortfolioValuation(
                as_of_date=day_date,
                base_currency=policy.base_currency,
                positions=[],
                total_value=Decimal("0"),
            )
            positions_value = Decimal("0")

        # --- Contribution ---
        contribution = schedule_map.get(day_date, Decimal("0"))
        if contribution > Decimal("0"):
            cash += contribution

        # --- Allocate & trade ---
        allocation: AllocationResult | None = None
        if contribution > Decimal("0"):
            allocation = allocate_contribution(
                state=valuation,
                policy=policy,
                amount=contribution,
                currency=policy.base_currency,
                include_satellite=sim_input.include_satellite,
            )

            if allocation.trades:
                day_costs = _execute_trades(allocation.trades, holdings, day_prices, day_fx, ticker_info, policy)
                cash -= allocation.total_allocated + day_costs
                cumulative_costs += day_costs
                cumulative_traded_value += allocation.total_allocated

                # Re-value after trades
                position_inputs = _build_position_inputs(holdings, ticker_info)
                if position_inputs:
                    updated_valuation = valuate_portfolio(day_date, position_inputs, day_prices, day_fx)
                    positions_value = updated_valuation.total_value

        # --- Record equity curve row ---
        equity = positions_value + cash
        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > Decimal("0") else Decimal("0")

        curve.append(
            EquityCurveRow(
                date=day_date,
                equity=equity,
                cash=cash,
                positions_value=positions_value,
                drawdown=drawdown,
                cumulative_costs=cumulative_costs,
                contribution_today=contribution,
                cumulative_traded_value=cumulative_traded_value,
            )
        )

    metrics = _compute_metrics(curve)
    curve_hash = _compute_curve_hash(curve)

    return SimulationResult(
        curve=curve,
        metrics=metrics,
        curve_hash=curve_hash,
        policy_hash=policy.policy_hash,
    )
