from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import DataMissingError, ValidationError
from app.domain.policy import (
    BucketConfig,
    BucketsConfig,
    ConstraintsConfig,
    CostsConfig,
    PolicyConfig,
    RebalancingConfig,
)
from app.domain.simulator import (
    ScheduledContribution,
    SimulationInput,
    TickerInfo,
    run_simulation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

D = Decimal


_ZERO = D("0")
_ONE = D("1")


def _make_policy(
    core_targets: dict[str, Decimal],
    satellite_targets: dict[str, Decimal] | None = None,
    min_trade_value: Decimal = _ZERO,
    max_position_weight: Decimal = _ONE,
    commission_fixed: Decimal = _ZERO,
    fx_spread_bps: int = 0,
) -> PolicyConfig:
    satellite = BucketConfig(targets=satellite_targets) if satellite_targets is not None else None
    return PolicyConfig(
        base_currency="EUR",
        buckets=BucketsConfig(
            core=BucketConfig(targets=core_targets),
            satellite=satellite,
        ),
        constraints=ConstraintsConfig(
            min_trade_value=min_trade_value,
            max_position_weight=max_position_weight,
        ),
        rebalancing=RebalancingConfig(),
        costs=CostsConfig(commission_fixed=commission_fixed, fx_spread_bps=fx_spread_bps),
        policy_hash="testhash123",
    )


def _make_ticker_info(*tickers_and_ccys: tuple[str, str]) -> dict[str, TickerInfo]:
    return {t: TickerInfo(ticker=t, currency=c) for t, c in tickers_and_ccys}


def _make_simple_input(
    policy: PolicyConfig | None = None,
    schedule: list[ScheduledContribution] | None = None,
    prices: dict[date, dict[str, Decimal]] | None = None,
    fx_rates: dict[date, dict[str, Decimal]] | None = None,
    ticker_info: dict[str, TickerInfo] | None = None,
    include_satellite: bool = False,
) -> SimulationInput:
    """Build a SimulationInput with sensible defaults for a 2-ticker EUR-only scenario.

    Default scenario: 2 EUR tickers (AAA 60%, BBB 40%), 3 days of flat prices at 100,
    single contribution of 1000 EUR on day 1.
    """
    if policy is None:
        policy = _make_policy(core_targets={"AAA": D("0.6"), "BBB": D("0.4")})

    if ticker_info is None:
        ticker_info = _make_ticker_info(("AAA", "EUR"), ("BBB", "EUR"))

    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    if prices is None:
        prices = {
            day1: {"AAA": D("100"), "BBB": D("100")},
            day2: {"AAA": D("100"), "BBB": D("100")},
            day3: {"AAA": D("100"), "BBB": D("100")},
        }

    if schedule is None:
        schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    if fx_rates is None:
        fx_rates = {}

    return SimulationInput(
        policy=policy,
        schedule=schedule,
        prices=prices,
        fx_rates=fx_rates,
        ticker_info=ticker_info,
        include_satellite=include_satellite,
    )


# ---------------------------------------------------------------------------
# A. Determinism (mandatory)
# ---------------------------------------------------------------------------


def test_determinism_same_inputs_same_result():
    """Same inputs produce identical curve_hash, curve rows, and metrics."""
    sim_input = _make_simple_input()

    result1 = run_simulation(sim_input)
    result2 = run_simulation(sim_input)

    assert result1.curve_hash == result2.curve_hash
    assert len(result1.curve) == len(result2.curve)
    for r1, r2 in zip(result1.curve, result2.curve, strict=True):
        assert r1 == r2
    assert result1.metrics == result2.metrics
    assert result1.policy_hash == result2.policy_hash


def test_curve_hash_changes_with_different_prices():
    """Different price inputs produce different curve hashes."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)

    prices_a = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
    }
    prices_b = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("105"), "BBB": D("100")},
    }

    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    result_a = run_simulation(_make_simple_input(prices=prices_a, schedule=schedule))
    result_b = run_simulation(_make_simple_input(prices=prices_b, schedule=schedule))

    assert result_a.curve_hash != result_b.curve_hash


# ---------------------------------------------------------------------------
# B. Basic simulation mechanics
# ---------------------------------------------------------------------------


def test_single_contribution_empty_portfolio():
    """A single contribution on day 1 buys shares; equity tracks value + cash.

    With 60/40 targets, 1000 EUR contribution, flat prices at 100:
    - AAA gets 600 EUR → 6 shares
    - BBB gets 400 EUR → 4 shares
    - total_allocated = 1000, cash after = 0 (no costs)
    """
    sim_input = _make_simple_input()
    result = run_simulation(sim_input)

    assert len(result.curve) == 3
    # Day 1: contribution + trades
    row1 = result.curve[0]
    assert row1.contribution_today == D("1000")
    assert row1.positions_value == D("1000")  # 6*100 + 4*100 = 1000
    assert row1.equity == row1.positions_value + row1.cash


def test_no_trades_on_non_contribution_days():
    """Holdings quantities do not change between contribution days."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("110"), "BBB": D("90")},
        day3: {"AAA": D("120"), "BBB": D("80")},
    }
    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    # Equity should change due to price movement, but contribution_today = 0 on days 2-3
    assert result.curve[1].contribution_today == D("0")
    assert result.curve[2].contribution_today == D("0")

    # Positions value should reflect new prices
    # Day 1: 6*100 + 4*100 = 1000
    # Day 2: 6*110 + 4*90 = 660 + 360 = 1020
    # Day 3: 6*120 + 4*80 = 720 + 320 = 1040
    assert result.curve[1].positions_value == D("1020")
    assert result.curve[2].positions_value == D("1040")


def test_multiple_contributions():
    """Two contributions on different days both trigger allocations."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    schedule = [
        ScheduledContribution(date=day1, amount=D("1000"), currency="EUR"),
        ScheduledContribution(date=day3, amount=D("500"), currency="EUR"),
    ]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
        day3: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    assert result.curve[0].contribution_today == D("1000")
    assert result.curve[1].contribution_today == D("0")
    assert result.curve[2].contribution_today == D("500")
    assert result.metrics.total_contributions == D("1500")


def test_equity_equals_positions_plus_cash():
    """The equity = positions_value + cash invariant holds on every row."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("110"), "BBB": D("95")},
        day3: {"AAA": D("105"), "BBB": D("102")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    for row in result.curve:
        assert row.equity == row.positions_value + row.cash, f"Invariant broken on {row.date}"


# ---------------------------------------------------------------------------
# C. Cost modeling
# ---------------------------------------------------------------------------


def test_commission_deducted_per_trade():
    """Commission is charged per trade and tracked in cumulative_costs.

    2 tickers → 2 trades, commission_fixed = 5.00 → 10.00 total costs.
    """
    policy = _make_policy(
        core_targets={"AAA": D("0.6"), "BBB": D("0.4")},
        commission_fixed=D("5"),
    )
    sim_input = _make_simple_input(policy=policy)
    result = run_simulation(sim_input)

    # 2 trades × 5 EUR = 10 EUR costs
    assert result.curve[0].cumulative_costs == D("10")
    assert result.metrics.total_costs == D("10")

    # Cash should be negative by the commission amount:
    # Received 1000, allocated ~1000, then deducted 10 in commissions
    assert result.curve[0].cash < D("0")


def test_fx_spread_reduces_shares_bought():
    """FX spread means fewer shares are bought compared to zero spread.

    Ticker USD_TICKER trades in USD. FX rate: 1 USD = 0.90 EUR.
    With 50 bps spread, we get fewer USD per EUR spent.
    """
    day1 = date(2024, 1, 15)

    # Single ticker in USD, 100% weight
    policy_no_spread = _make_policy(
        core_targets={"USD_TICKER": D("1")},
        fx_spread_bps=0,
    )
    policy_with_spread = _make_policy(
        core_targets={"USD_TICKER": D("1")},
        fx_spread_bps=50,
    )

    ticker_info = _make_ticker_info(("USD_TICKER", "USD"))
    prices = {day1: {"USD_TICKER": D("10")}}
    fx_rates = {day1: {"USD/EUR": D("0.90")}}
    schedule = [ScheduledContribution(date=day1, amount=D("900"), currency="EUR")]

    result_no_spread = run_simulation(
        SimulationInput(
            policy=policy_no_spread,
            schedule=schedule,
            prices=prices,
            fx_rates=fx_rates,
            ticker_info=ticker_info,
            include_satellite=False,
        )
    )
    result_with_spread = run_simulation(
        SimulationInput(
            policy=policy_with_spread,
            schedule=schedule,
            prices=prices,
            fx_rates=fx_rates,
            ticker_info=ticker_info,
            include_satellite=False,
        )
    )

    # With spread, positions_value should be lower (fewer shares bought)
    assert result_with_spread.curve[0].positions_value < result_no_spread.curve[0].positions_value
    # And costs should be > 0
    assert result_with_spread.curve[0].cumulative_costs > D("0")


def test_zero_costs_when_zero_configured():
    """No costs accrue when commission and spread are both zero."""
    sim_input = _make_simple_input()
    result = run_simulation(sim_input)

    assert result.metrics.total_costs == D("0")
    assert result.curve[-1].cumulative_costs == D("0")


# ---------------------------------------------------------------------------
# D. Drawdown
# ---------------------------------------------------------------------------


def test_drawdown_zero_when_prices_only_rise():
    """If equity only rises, drawdown is always 0."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("110"), "BBB": D("110")},
        day3: {"AAA": D("120"), "BBB": D("120")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    for row in result.curve:
        assert row.drawdown == D("0"), f"Drawdown should be 0 on {row.date}"


def test_drawdown_computed_correctly():
    """Drawdown reflects the drop from peak equity.

    Day 1: contribute 1000, buy at 100 → equity = 1000 (peak)
    Day 2: prices drop 10% → equity = 900 → drawdown = 100/1000 = 0.1
    Day 3: prices recover to 95 → equity = 950 → drawdown = 50/1000 = 0.05
    """
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("90"), "BBB": D("90")},
        day3: {"AAA": D("95"), "BBB": D("95")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    # Day 1: equity ~= 1000 (peak), drawdown = 0
    assert result.curve[0].drawdown == D("0")
    # Day 2: equity ~= 900, peak = 1000, drawdown = 100/1000 = 0.1
    assert result.curve[1].drawdown == D("0.1")
    # Day 3: equity ~= 950, peak still 1000, drawdown = 50/1000 = 0.05
    assert result.curve[2].drawdown == D("0.05")


# ---------------------------------------------------------------------------
# E. Metrics
# ---------------------------------------------------------------------------


def test_total_return_computed():
    """Total return = (final_equity - total_contributions) / total_contributions.

    Contribute 1000, prices go up 10% → final equity = 1100.
    Total return = (1100 - 1000) / 1000 = 0.1
    """
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("110"), "BBB": D("110")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    assert result.metrics.total_return == D("0.1")
    assert result.metrics.total_contributions == D("1000")
    assert result.metrics.final_equity == D("1100")


def test_cagr_none_for_short_period():
    """CAGR is None when simulation is shorter than 365 days."""
    sim_input = _make_simple_input()
    result = run_simulation(sim_input)

    assert result.metrics.cagr is None


def test_cagr_computed_for_long_period():
    """CAGR is computed when simulation spans >= 365 days.

    Contribute 1000, flat prices for 400 days → CAGR = 0 (no growth).
    """
    start = date(2023, 1, 1)
    schedule = [ScheduledContribution(date=start, amount=D("1000"), currency="EUR")]

    # Generate 400 days of flat prices
    prices: dict[date, dict[str, Decimal]] = {}
    from datetime import timedelta

    for i in range(400):
        d = start + timedelta(days=i)
        prices[d] = {"AAA": D("100"), "BBB": D("100")}

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    assert result.metrics.cagr is not None
    # Flat prices, no costs → CAGR should be ~0
    assert abs(result.metrics.cagr) < D("0.001")


def test_max_drawdown_matches_curve():
    """max_drawdown in metrics equals the maximum drawdown found in curve rows."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("80"), "BBB": D("80")},
        day3: {"AAA": D("90"), "BBB": D("90")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    curve_max_dd = max(row.drawdown for row in result.curve)
    assert result.metrics.max_drawdown == curve_max_dd


# ---------------------------------------------------------------------------
# F. Validation errors
# ---------------------------------------------------------------------------


def test_empty_schedule_raises():
    sim_input = _make_simple_input(schedule=[])
    with pytest.raises(ValidationError, match="schedule must not be empty"):
        run_simulation(sim_input)


def test_currency_mismatch_raises():
    schedule = [ScheduledContribution(date=date(2024, 1, 15), amount=D("1000"), currency="USD")]
    sim_input = _make_simple_input(schedule=schedule)
    with pytest.raises(ValidationError, match="does not match policy base currency"):
        run_simulation(sim_input)


def test_missing_ticker_info_raises():
    ticker_info = _make_ticker_info(("AAA", "EUR"))  # Missing BBB
    sim_input = _make_simple_input(ticker_info=ticker_info)
    with pytest.raises(ValidationError, match="Missing ticker_info"):
        run_simulation(sim_input)


def test_missing_prices_for_contribution_date_raises():
    schedule = [ScheduledContribution(date=date(2024, 2, 1), amount=D("1000"), currency="EUR")]
    sim_input = _make_simple_input(schedule=schedule)
    with pytest.raises(DataMissingError, match="Missing price data"):
        run_simulation(sim_input)


def test_negative_contribution_raises():
    schedule = [ScheduledContribution(date=date(2024, 1, 15), amount=D("-100"), currency="EUR")]
    sim_input = _make_simple_input(schedule=schedule)
    with pytest.raises(ValidationError, match="must be positive"):
        run_simulation(sim_input)


# ---------------------------------------------------------------------------
# G. Edge cases
# ---------------------------------------------------------------------------


def test_single_day_simulation():
    """Simulation with only one day of price data."""
    day1 = date(2024, 1, 15)
    prices = {day1: {"AAA": D("100"), "BBB": D("100")}}
    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    sim_input = _make_simple_input(prices=prices, schedule=schedule)
    result = run_simulation(sim_input)

    assert len(result.curve) == 1
    assert result.curve[0].equity > D("0")


def test_all_base_currency_tickers_no_fx_needed():
    """All tickers in EUR means no FX rates are needed."""
    sim_input = _make_simple_input(fx_rates={})
    result = run_simulation(sim_input)

    assert len(result.curve) == 3
    assert result.metrics.total_costs == D("0")


def test_contribution_on_last_day():
    """Contribution on the last day still produces correct results."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    schedule = [ScheduledContribution(date=day3, amount=D("1000"), currency="EUR")]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
        day3: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    # Days 1-2: no contribution, equity = 0
    assert result.curve[0].equity == D("0")
    assert result.curve[1].equity == D("0")
    # Day 3: contribution + trades
    assert result.curve[2].contribution_today == D("1000")
    assert result.curve[2].equity > D("0")


def test_policy_hash_in_result():
    """The result carries the policy hash from the input policy."""
    sim_input = _make_simple_input()
    result = run_simulation(sim_input)

    assert result.policy_hash == "testhash123"


def test_pre_contribution_days_have_zero_equity():
    """Days before any contribution show zero equity."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    schedule = [ScheduledContribution(date=day2, amount=D("1000"), currency="EUR")]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
        day3: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    assert result.curve[0].equity == D("0")
    assert result.curve[0].cash == D("0")
    assert result.curve[0].positions_value == D("0")


# ---------------------------------------------------------------------------
# H. Realistic scenario with hand-calculated values
# ---------------------------------------------------------------------------


def test_scenario_two_eur_tickers_single_contribution():
    """Full trace: 2 EUR tickers, 60/40 split, 1000 EUR, 3 days.

    Day 1 (2024-01-15):
      Contribution: 1000 EUR
      Allocator targets: AAA=60%, BBB=40%
      Portfolio is empty → full gap → proportional allocation
      AAA buy: 600.00 EUR → 600/50 = 12 shares
      BBB buy: 400.00 EUR → 400/25 = 16 shares
      Total allocated: 1000 EUR, unallocated: 0, costs: 0
      Cash: 1000 - 1000 = 0
      Positions: AAA=12*50=600, BBB=16*25=400 → total=1000
      Equity: 1000 + 0 = 1000

    Day 2 (2024-01-16): prices change
      AAA: 55 → 12*55 = 660
      BBB: 24 → 16*24 = 384
      Positions: 1044, cash: 0, equity: 1044
      Peak: 1044, drawdown: 0

    Day 3 (2024-01-17): prices drop
      AAA: 48 → 12*48 = 576
      BBB: 22 → 16*22 = 352
      Positions: 928, cash: 0, equity: 928
      Peak: 1044, drawdown: (1044-928)/1044 = 116/1044
    """
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("50"), "BBB": D("25")},
        day2: {"AAA": D("55"), "BBB": D("24")},
        day3: {"AAA": D("48"), "BBB": D("22")},
    }
    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    sim_input = _make_simple_input(prices=prices, schedule=schedule)
    result = run_simulation(sim_input)

    assert len(result.curve) == 3

    # Day 1
    row1 = result.curve[0]
    assert row1.contribution_today == D("1000")
    assert row1.positions_value == D("1000")
    assert row1.cash == D("0")
    assert row1.equity == D("1000")
    assert row1.drawdown == D("0")

    # Day 2
    row2 = result.curve[1]
    assert row2.positions_value == D("1044")
    assert row2.cash == D("0")
    assert row2.equity == D("1044")
    assert row2.drawdown == D("0")

    # Day 3
    row3 = result.curve[2]
    assert row3.positions_value == D("928")
    assert row3.cash == D("0")
    assert row3.equity == D("928")
    expected_dd = (D("1044") - D("928")) / D("1044")
    assert row3.drawdown == expected_dd

    # Metrics
    assert result.metrics.total_contributions == D("1000")
    assert result.metrics.final_equity == D("928")
    assert result.metrics.total_return == (D("928") - D("1000")) / D("1000")
    assert result.metrics.max_drawdown == expected_dd
    assert result.metrics.total_costs == D("0")

    # Turnover: traded 1000 / avg equity = (1000+1044+928)/3
    avg_eq = (D("1000") + D("1044") + D("928")) / 3
    assert abs(result.metrics.turnover - D("1000") / avg_eq) < D("0.0001")

    # Volatility: computed (3 days, 2 return observations)
    assert result.metrics.annualized_volatility is not None
    assert result.metrics.annualized_volatility > D("0")

    # cumulative_traded_value only set on day 1
    assert row1.cumulative_traded_value == D("1000")
    assert row2.cumulative_traded_value == D("1000")
    assert row3.cumulative_traded_value == D("1000")


def test_scenario_with_commission_costs():
    """Commission of 3 EUR per trade on 2 trades = 6 EUR total.

    Contribution: 1000 EUR, 2 tickers, flat prices at 100.
    Allocator allocates ~1000 EUR across 2 trades.
    Commission: 2 × 3 = 6 EUR from cash.
    Cash after: 1000 - allocated - 6
    """
    day1 = date(2024, 1, 15)

    policy = _make_policy(
        core_targets={"AAA": D("0.6"), "BBB": D("0.4")},
        commission_fixed=D("3"),
    )
    prices = {day1: {"AAA": D("100"), "BBB": D("100")}}
    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    sim_input = _make_simple_input(policy=policy, prices=prices, schedule=schedule)
    result = run_simulation(sim_input)

    row = result.curve[0]
    assert row.cumulative_costs == D("6")
    # Cash = 1000 (contribution) - total_allocated - 6 (costs)
    # The allocator gets full 1000, allocates ~1000. So cash ≈ -6.
    assert row.cash < D("0")
    assert row.equity == row.positions_value + row.cash


def test_scenario_fx_ticker_with_spread():
    """Single USD ticker, 100% weight, 0.5% FX spread.

    FX rate: 1 USD = 0.90 EUR (so 1 EUR = 1/0.90 USD = 1.111... USD)
    Contribution: 900 EUR

    Without spread:
      local_amount = 900 / 0.90 = 1000 USD
      shares = 1000 / 10 = 100

    With 50 bps spread:
      spread_factor = 1 - 50/10000 = 0.995
      local_amount = (900 / 0.90) * 0.995 = 1000 * 0.995 = 995 USD
      shares = 995 / 10 = 99.5
      fx_cost = (1000 - 995) * 0.90 = 5 * 0.90 = 4.50 EUR
    """
    day1 = date(2024, 1, 15)

    policy = _make_policy(
        core_targets={"USD_TICKER": D("1")},
        fx_spread_bps=50,
    )
    ticker_info = _make_ticker_info(("USD_TICKER", "USD"))
    prices = {day1: {"USD_TICKER": D("10")}}
    fx_rates = {day1: {"USD/EUR": D("0.90")}}
    schedule = [ScheduledContribution(date=day1, amount=D("900"), currency="EUR")]

    sim_input = SimulationInput(
        policy=policy,
        schedule=schedule,
        prices=prices,
        fx_rates=fx_rates,
        ticker_info=ticker_info,
        include_satellite=False,
    )
    result = run_simulation(sim_input)

    row = result.curve[0]
    # FX cost = 4.50 EUR
    assert row.cumulative_costs == D("4.5")
    # Positions: 99.5 shares × 10 USD × 0.90 EUR/USD = 895.50 EUR
    assert row.positions_value == D("895.50")


# ---------------------------------------------------------------------------
# I. Volatility
# ---------------------------------------------------------------------------


def test_volatility_none_for_single_day():
    """Volatility is None when there's only 1 day (< 2 return observations)."""
    day1 = date(2024, 1, 15)
    prices = {day1: {"AAA": D("100"), "BBB": D("100")}}
    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    sim_input = _make_simple_input(prices=prices, schedule=schedule)
    result = run_simulation(sim_input)

    assert result.metrics.annualized_volatility is None


def test_volatility_none_for_two_days_pre_contribution():
    """Volatility is None when equity is zero on all but last day (< 2 observations)."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)

    schedule = [ScheduledContribution(date=day2, amount=D("1000"), currency="EUR")]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    # Day 1: equity=0, Day 2: equity=1000. Only 1 return can be computed (day1→day2),
    # but prev_equity=0 so it's skipped. Result: 0 observations → None.
    assert result.metrics.annualized_volatility is None


def test_volatility_zero_for_flat_prices():
    """Flat prices with a single contribution on day 1 → vol = 0."""
    sim_input = _make_simple_input()  # 3 days, flat prices at 100
    result = run_simulation(sim_input)

    # Daily returns are all 0 → stdev = 0 → vol = 0
    assert result.metrics.annualized_volatility == D("0")


def test_volatility_positive_for_varying_prices():
    """Varying prices produce positive volatility."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("110"), "BBB": D("90")},
        day3: {"AAA": D("105"), "BBB": D("95")},
    }

    sim_input = _make_simple_input(prices=prices)
    result = run_simulation(sim_input)

    assert result.metrics.annualized_volatility is not None
    assert result.metrics.annualized_volatility > D("0")


def test_volatility_adjusts_for_contributions():
    """TWR adjustment removes contribution effect from volatility.

    Single-ticker portfolio eliminates reallocation composition effects,
    so both scenarios should produce the same volatility despite the
    second one having an additional contribution.
    """
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    policy = _make_policy(core_targets={"AAA": D("1")})
    ticker_info = _make_ticker_info(("AAA", "EUR"))
    prices = {
        day1: {"AAA": D("100")},
        day2: {"AAA": D("110")},
        day3: {"AAA": D("105")},
    }

    # Scenario A: single contribution
    schedule_a = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]
    result_a = run_simulation(
        _make_simple_input(policy=policy, ticker_info=ticker_info, prices=prices, schedule=schedule_a)
    )

    # Scenario B: two contributions (day 1 + day 2)
    schedule_b = [
        ScheduledContribution(date=day1, amount=D("1000"), currency="EUR"),
        ScheduledContribution(date=day2, amount=D("500"), currency="EUR"),
    ]
    result_b = run_simulation(
        _make_simple_input(policy=policy, ticker_info=ticker_info, prices=prices, schedule=schedule_b)
    )

    assert result_a.metrics.annualized_volatility is not None
    assert result_b.metrics.annualized_volatility is not None

    # With TWR adjustment and single-ticker, the price-driven returns are identical
    # despite the extra contribution in scenario B.
    assert abs(result_a.metrics.annualized_volatility - result_b.metrics.annualized_volatility) < D("0.01")


def test_volatility_hand_calculated():
    """Verify volatility against hand-calculated values.

    Day 1: contribute 1000, buy at 50/25 → equity = 1000
    Day 2: AAA=55, BBB=24 → equity = 12*55 + 16*24 = 660+384 = 1044
    Day 3: AAA=48, BBB=22 → equity = 12*48 + 16*22 = 576+352 = 928

    Daily returns (no contributions on days 2,3):
      r1 = (1044 - 1000) / 1000 = 0.044
      r2 = (928 - 1044) / 1044 = -116/1044

    mean = (0.044 + (-116/1044)) / 2
    variance = ((r1-mean)^2 + (r2-mean)^2) / 1  (sample variance, n-1=1)
    stdev = sqrt(variance)
    annualized_vol = stdev * sqrt(252)
    """
    import math

    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    prices = {
        day1: {"AAA": D("50"), "BBB": D("25")},
        day2: {"AAA": D("55"), "BBB": D("24")},
        day3: {"AAA": D("48"), "BBB": D("22")},
    }
    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]

    sim_input = _make_simple_input(prices=prices, schedule=schedule)
    result = run_simulation(sim_input)

    r1 = D("44") / D("1000")  # 0.044
    r2 = D("-116") / D("1044")
    mean = (r1 + r2) / 2
    var = ((r1 - mean) ** 2 + (r2 - mean) ** 2) / 1
    expected_vol = D(str(math.sqrt(float(var)))) * D(str(math.sqrt(252)))

    assert result.metrics.annualized_volatility is not None
    assert abs(result.metrics.annualized_volatility - expected_vol) < D("0.0001")


# ---------------------------------------------------------------------------
# J. Turnover
# ---------------------------------------------------------------------------


def test_turnover_single_contribution_flat_prices():
    """Single contribution of 1000 EUR, flat prices at 100.

    total_traded_value = 1000 (full contribution allocated)
    avg_equity = 1000 (constant across 3 days)
    turnover = 1000 / 1000 = 1.0
    """
    sim_input = _make_simple_input()
    result = run_simulation(sim_input)

    assert result.metrics.turnover == D("1")


def test_turnover_multiple_contributions():
    """Two contributions accumulate traded value."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    schedule = [
        ScheduledContribution(date=day1, amount=D("1000"), currency="EUR"),
        ScheduledContribution(date=day3, amount=D("500"), currency="EUR"),
    ]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
        day3: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    # total_traded = 1000 + 500 = 1500
    assert result.curve[-1].cumulative_traded_value == D("1500")
    # avg equity = (1000 + 1000 + 1500) / 3 = 3500/3
    avg_eq = D("3500") / D("3")
    expected_turnover = D("1500") / avg_eq
    assert abs(result.metrics.turnover - expected_turnover) < D("0.0001")


def test_cumulative_traded_value_in_curve():
    """cumulative_traded_value increases only on contribution days."""
    day1 = date(2024, 1, 15)
    day2 = date(2024, 1, 16)
    day3 = date(2024, 1, 17)

    schedule = [ScheduledContribution(date=day1, amount=D("1000"), currency="EUR")]
    prices = {
        day1: {"AAA": D("100"), "BBB": D("100")},
        day2: {"AAA": D("100"), "BBB": D("100")},
        day3: {"AAA": D("100"), "BBB": D("100")},
    }

    sim_input = _make_simple_input(schedule=schedule, prices=prices)
    result = run_simulation(sim_input)

    # Traded on day 1 only
    assert result.curve[0].cumulative_traded_value == D("1000")
    assert result.curve[1].cumulative_traded_value == D("1000")
    assert result.curve[2].cumulative_traded_value == D("1000")


def test_turnover_with_costs():
    """Commission costs do not inflate traded value."""
    policy = _make_policy(
        core_targets={"AAA": D("0.6"), "BBB": D("0.4")},
        commission_fixed=D("5"),
    )
    sim_input = _make_simple_input(policy=policy)
    result = run_simulation(sim_input)

    # traded value = total_allocated = 1000 (the contribution amount),
    # not 1000 + 10 (costs). Costs are separate.
    assert result.curve[0].cumulative_traded_value == D("1000")
