from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.run_backtest import RunBacktestResult, _expand_monthly_schedule, run_backtest
from app.core.errors import DataMissingError, ValidationError
from app.domain.backtest import MonthlySchedule
from app.domain.simulator import ScheduledContribution
from app.infrastructure.db.models import Asset
from app.infrastructure.db.repositories import PolicyRepository, PriceInput, PricesRepository

VALID_POLICY_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.40
"""

BACKTEST_YAML = """\
start_date: 2024-01-15
end_date: 2024-03-15
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
  day_of_month: 15
"""


async def _seed_policy(session: AsyncSession) -> int:
    repo = PolicyRepository(session)
    policy = await repo.save("test-policy", VALID_POLICY_YAML, "testhash")
    await session.flush()
    return policy.id


async def _seed_prices(session: AsyncSession) -> None:
    """Seed assets and daily prices for IWDA.AS and EIMI.AS."""
    iwda = Asset(ticker="IWDA.AS", currency="EUR", asset_type="equity")
    eimi = Asset(ticker="EIMI.AS", currency="EUR", asset_type="equity")
    session.add_all([iwda, eimi])
    await session.flush()

    prices_repo = PricesRepository(session)
    ticker_to_asset = {"IWDA.AS": iwda, "EIMI.AS": eimi}

    # Generate daily prices for the backtest period
    prices: list[PriceInput] = []
    d = date(2024, 1, 15)
    while d <= date(2024, 3, 15):
        prices.append(PriceInput(ticker="IWDA.AS", date=d, close=Decimal("80.00"), currency="EUR"))
        prices.append(PriceInput(ticker="EIMI.AS", date=d, close=Decimal("30.00"), currency="EUR"))
        d = date.fromordinal(d.toordinal() + 1)

    await prices_repo.upsert_prices(prices, ticker_to_asset)
    await session.flush()


# ---------------------------------------------------------------------------
# Monthly schedule expansion tests
# ---------------------------------------------------------------------------


def test_expand_monthly_schedule_basic() -> None:
    schedule = MonthlySchedule(amount=Decimal("1000"), currency="EUR", day_of_month=15)
    result = _expand_monthly_schedule(schedule, date(2024, 1, 1), date(2024, 3, 31))
    assert len(result) == 3
    assert result[0] == ScheduledContribution(date=date(2024, 1, 15), amount=Decimal("1000"), currency="EUR")
    assert result[1].date == date(2024, 2, 15)
    assert result[2].date == date(2024, 3, 15)


def test_expand_monthly_schedule_skips_before_start() -> None:
    schedule = MonthlySchedule(amount=Decimal("500"), currency="EUR", day_of_month=1)
    result = _expand_monthly_schedule(schedule, date(2024, 1, 15), date(2024, 3, 31))
    assert len(result) == 2
    assert result[0].date == date(2024, 2, 1)
    assert result[1].date == date(2024, 3, 1)


def test_expand_monthly_schedule_start_on_day() -> None:
    schedule = MonthlySchedule(amount=Decimal("500"), currency="EUR", day_of_month=15)
    result = _expand_monthly_schedule(schedule, date(2024, 1, 15), date(2024, 1, 15))
    assert len(result) == 1
    assert result[0].date == date(2024, 1, 15)


def test_expand_monthly_schedule_crosses_year_boundary() -> None:
    schedule = MonthlySchedule(amount=Decimal("100"), currency="EUR", day_of_month=10)
    result = _expand_monthly_schedule(schedule, date(2024, 11, 1), date(2025, 2, 28))
    dates = [c.date for c in result]
    assert dates == [date(2024, 11, 10), date(2024, 12, 10), date(2025, 1, 10), date(2025, 2, 10)]


def test_expand_monthly_schedule_empty_when_no_dates_fit() -> None:
    schedule = MonthlySchedule(amount=Decimal("100"), currency="EUR", day_of_month=28)
    result = _expand_monthly_schedule(schedule, date(2024, 1, 1), date(2024, 1, 10))
    assert result == []


# ---------------------------------------------------------------------------
# run_backtest integration tests
# ---------------------------------------------------------------------------


async def test_run_backtest_happy_path(session: AsyncSession) -> None:
    policy_id = await _seed_policy(session)
    await _seed_prices(session)

    result = await run_backtest(policy_id, BACKTEST_YAML, include_satellite=False, session=session)
    await session.commit()

    assert isinstance(result, RunBacktestResult)
    assert result.run_id is not None
    assert result.policy_id == policy_id
    assert result.start_date == date(2024, 1, 15)
    assert result.end_date == date(2024, 3, 15)
    assert len(result.config_hash) == 64
    assert len(result.policy_hash) == 64
    assert len(result.curve_hash) == 64


async def test_run_backtest_raises_when_policy_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError, match="Policy not found"):
        await run_backtest(99999, BACKTEST_YAML, include_satellite=False, session=session)


async def test_run_backtest_raises_on_invalid_yaml(session: AsyncSession) -> None:
    policy_id = await _seed_policy(session)
    with pytest.raises(ValidationError):
        await run_backtest(policy_id, "not: valid: yaml: [", include_satellite=False, session=session)


async def test_run_backtest_raises_when_no_asset_data(session: AsyncSession) -> None:
    policy_id = await _seed_policy(session)
    # No prices seeded
    with pytest.raises(DataMissingError, match="No asset data found"):
        await run_backtest(policy_id, BACKTEST_YAML, include_satellite=False, session=session)


async def test_run_backtest_determinism(session: AsyncSession) -> None:
    policy_id = await _seed_policy(session)
    await _seed_prices(session)

    r1 = await run_backtest(policy_id, BACKTEST_YAML, include_satellite=False, session=session)
    await session.commit()

    r2 = await run_backtest(policy_id, BACKTEST_YAML, include_satellite=False, session=session)
    await session.commit()

    assert r1.curve_hash == r2.curve_hash
    assert r1.policy_hash == r2.policy_hash
    assert r1.config_hash == r2.config_hash


async def test_run_backtest_csv_schedule(session: AsyncSession) -> None:
    policy_id = await _seed_policy(session)
    await _seed_prices(session)

    csv_yaml = """\
start_date: 2024-01-15
end_date: 2024-03-15
contribution_schedule:
  type: csv
  contributions:
    - date: 2024-01-15
      amount: 500
      currency: EUR
    - date: 2024-02-15
      amount: 750
      currency: EUR
"""

    result = await run_backtest(policy_id, csv_yaml, include_satellite=False, session=session)
    await session.commit()

    assert isinstance(result, RunBacktestResult)
    assert result.start_date == date(2024, 1, 15)
    assert result.end_date == date(2024, 3, 15)
