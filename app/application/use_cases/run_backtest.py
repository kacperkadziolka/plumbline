from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.domain.backtest import CsvSchedule, MonthlySchedule, parse_backtest_yaml
from app.domain.policy import parse_policy_yaml
from app.domain.simulator import (
    ScheduledContribution,
    SimulationInput,
    TickerInfo,
    run_simulation,
)
from app.infrastructure.db.repositories import FxRepository, PolicyRepository, PricesRepository

from .save_backtest_run import save_backtest_run


class RunBacktestResult(BaseModel):
    run_id: int
    policy_id: int
    config_hash: str
    policy_hash: str
    curve_hash: str
    start_date: date
    end_date: date


def _expand_monthly_schedule(
    schedule: MonthlySchedule,
    start_date: date,
    end_date: date,
) -> list[ScheduledContribution]:
    contributions: list[ScheduledContribution] = []
    current = date(start_date.year, start_date.month, schedule.day_of_month)
    if current < start_date:
        # Advance to next month
        if current.month == 12:
            current = date(current.year + 1, 1, schedule.day_of_month)
        else:
            current = date(current.year, current.month + 1, schedule.day_of_month)
    while current <= end_date:
        contributions.append(ScheduledContribution(date=current, amount=schedule.amount, currency=schedule.currency))
        if current.month == 12:
            current = date(current.year + 1, 1, schedule.day_of_month)
        else:
            current = date(current.year, current.month + 1, schedule.day_of_month)
    return contributions


async def run_backtest(
    policy_id: int,
    backtest_yaml: str,
    include_satellite: bool,
    session: AsyncSession,
) -> RunBacktestResult:
    """Run a full backtest: parse config, load data, simulate, persist result.

    Note: Does not commit. Caller owns the transaction boundary.

    Raises:
        ValidationError: If YAML or config is invalid.
        DataMissingError: If policy, price data, or FX data is missing.
    """
    config = parse_backtest_yaml(backtest_yaml)

    # Load policy
    policy_repo = PolicyRepository(session)
    policy_row = await policy_repo.get_by_id(policy_id)
    if policy_row is None:
        raise DataMissingError(message="Policy not found", details=f"No policy with id={policy_id}")
    policy_config = parse_policy_yaml(policy_row.yaml_text)

    # Collect tickers
    tickers: set[str] = set(policy_config.buckets.core.targets.keys())
    if include_satellite and policy_config.buckets.satellite is not None:
        tickers |= set(policy_config.buckets.satellite.targets.keys())

    # Fetch asset info for TickerInfo
    prices_repo = PricesRepository(session)
    assets = await prices_repo.get_assets_by_tickers(tickers)
    missing_tickers = sorted(tickers - set(assets.keys()))
    if missing_tickers:
        raise DataMissingError(
            message="No asset data found for tickers",
            details=f"{', '.join(missing_tickers)}. Import price data first.",
        )

    ticker_info: dict[str, TickerInfo] = {
        ticker: TickerInfo(ticker=ticker, currency=asset.currency) for ticker, asset in assets.items()
    }

    # Load prices per ticker and pivot to date-keyed structure
    prices: dict[date, dict[str, Decimal]] = {}
    for ticker in sorted(tickers):
        price_rows = await prices_repo.get_prices(ticker, config.start_date, config.end_date)
        for row in price_rows:
            prices.setdefault(row.date, {})[ticker] = row.close

    # Determine FX pairs needed and load
    base_ccy = policy_config.base_currency
    fx_pairs: set[str] = set()
    for info in ticker_info.values():
        if info.currency != base_ccy:
            fx_pairs.add(f"{info.currency}/{base_ccy}")

    fx_repo = FxRepository(session)
    fx_rates: dict[date, dict[str, Decimal]] = {}
    for pair in sorted(fx_pairs):
        fx_rows = await fx_repo.get_fx_rates(pair, config.start_date, config.end_date)
        for fx_row in fx_rows:
            fx_rates.setdefault(fx_row.date, {})[pair] = fx_row.rate

    # Expand contribution schedule
    schedule = config.contribution_schedule
    if isinstance(schedule, MonthlySchedule):
        contributions = _expand_monthly_schedule(schedule, config.start_date, config.end_date)
    else:
        assert isinstance(schedule, CsvSchedule)
        contributions = [
            ScheduledContribution(date=c.date, amount=c.amount, currency=c.currency) for c in schedule.contributions
        ]

    # Run simulation
    sim_input = SimulationInput(
        policy=policy_config,
        schedule=contributions,
        prices=prices,
        fx_rates=fx_rates,
        ticker_info=ticker_info,
        include_satellite=include_satellite,
    )
    sim_result = run_simulation(sim_input)

    # Persist
    saved = await save_backtest_run(
        policy_id=policy_id,
        backtest_yaml=backtest_yaml,
        config_hash=config.config_hash,
        simulation_result=sim_result,
        start_date=config.start_date,
        end_date=config.end_date,
        session=session,
    )

    return RunBacktestResult(
        run_id=saved.run_id,
        policy_id=saved.policy_id,
        config_hash=saved.config_hash,
        policy_hash=saved.policy_hash,
        curve_hash=saved.curve_hash,
        start_date=saved.start_date,
        end_date=saved.end_date,
    )
