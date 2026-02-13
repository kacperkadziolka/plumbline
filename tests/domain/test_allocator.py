from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.domain.allocator import allocate_contribution
from app.domain.policy import (
    BucketConfig,
    BucketsConfig,
    ConstraintsConfig,
    CostsConfig,
    PolicyConfig,
    RebalancingConfig,
)
from app.domain.valuation import PortfolioValuation, PositionValuation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    core_targets: dict[str, Decimal],
    satellite_targets: dict[str, Decimal] | None = None,
    min_trade_value: Decimal = Decimal("0"),
    max_position_weight: Decimal = Decimal("1"),
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
        costs=CostsConfig(),
        policy_hash="testhash123",
    )


def _make_valuation(
    positions: list[tuple[str, str, Decimal]],
    total: Decimal | None = None,
) -> PortfolioValuation:
    """Build a PortfolioValuation from (ticker, currency, value_base) triples."""
    pvs = [
        PositionValuation(
            ticker=t,
            currency=c,
            qty=Decimal("1"),
            price=v,
            fx_rate=Decimal("1"),
            value_local=v,
            value_base=v,
        )
        for t, c, v in sorted(positions, key=lambda x: x[0])
    ]
    if total is None:
        total = sum((p.value_base for p in pvs), Decimal("0"))
    return PortfolioValuation(
        as_of_date=date(2024, 6, 15),
        base_currency="EUR",
        positions=pvs,
        total_value=total,
    )


# ---------------------------------------------------------------------------
# A. Sum allocations == contribution (epsilon)
# ---------------------------------------------------------------------------


def test_sum_allocations_equals_contribution() -> None:
    policy = _make_policy(
        core_targets={"IWDA.AS": Decimal("0.60"), "EIMI.AS": Decimal("0.25"), "IUSN.AS": Decimal("0.15")}
    )
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert result.total_allocated + result.unallocated == amount


def test_sum_allocations_with_satellite() -> None:
    policy = _make_policy(
        core_targets={"IWDA.AS": Decimal("0.60"), "EIMI.AS": Decimal("0.25"), "IUSN.AS": Decimal("0.15")},
        satellite_targets={"AAPL": Decimal("0.50"), "GOOGL": Decimal("0.50")},
    )
    state = _make_valuation([])
    amount = Decimal("2000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=True)

    assert result.total_allocated + result.unallocated == amount
    assert len(result.trades) == 5


def test_sum_allocations_with_existing_portfolio() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.60"), "B": Decimal("0.40")},
    )
    state = _make_valuation([("A", "EUR", Decimal("400")), ("B", "EUR", Decimal("600"))])
    amount = Decimal("500")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert result.total_allocated + result.unallocated == amount


# ---------------------------------------------------------------------------
# B. Only allowed universe
# ---------------------------------------------------------------------------


def test_core_only_excludes_satellite_tickers() -> None:
    policy = _make_policy(
        core_targets={"IWDA.AS": Decimal("0.60"), "EIMI.AS": Decimal("0.40")},
        satellite_targets={"AAPL": Decimal("0.50"), "TSLA": Decimal("0.50")},
    )
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    trade_tickers = {t.ticker for t in result.trades}
    assert trade_tickers == {"IWDA.AS", "EIMI.AS"}
    assert "AAPL" not in trade_tickers
    assert "TSLA" not in trade_tickers


def test_include_satellite_allows_all_tickers() -> None:
    policy = _make_policy(
        core_targets={"IWDA.AS": Decimal("0.60"), "EIMI.AS": Decimal("0.40")},
        satellite_targets={"AAPL": Decimal("0.50"), "TSLA": Decimal("0.50")},
    )
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=True)

    trade_tickers = {t.ticker for t in result.trades}
    assert "IWDA.AS" in trade_tickers
    assert "EIMI.AS" in trade_tickers
    assert "AAPL" in trade_tickers
    assert "TSLA" in trade_tickers


# ---------------------------------------------------------------------------
# C. min_trade_value behavior
# ---------------------------------------------------------------------------


def test_min_trade_value_drops_small_trades() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.90"), "B": Decimal("0.10")},
        min_trade_value=Decimal("200"),
    )
    # A is heavily overweight, B is underweight -> most allocation goes to B
    # But with a small contribution, B's share may be below min_trade
    state = _make_valuation([("A", "EUR", Decimal("9000")), ("B", "EUR", Decimal("0"))])
    amount = Decimal("500")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    for trade in result.trades:
        assert trade.buy_amount >= Decimal("200")
    assert result.total_allocated + result.unallocated == amount


def test_min_trade_value_zero_allows_all_trades() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.90"), "B": Decimal("0.10")},
        min_trade_value=Decimal("0"),
    )
    state = _make_valuation([])
    amount = Decimal("10")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert len(result.trades) == 2
    assert result.total_allocated + result.unallocated == amount


def test_contribution_too_small_for_any_trade() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.50"), "B": Decimal("0.50")},
        min_trade_value=Decimal("100"),
    )
    state = _make_valuation([])
    amount = Decimal("50")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert result.trades == []
    assert result.unallocated == amount


# ---------------------------------------------------------------------------
# D. max_position_weight behavior (soft clamp)
# ---------------------------------------------------------------------------


def test_max_weight_clamps_overweight_position() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.80"), "B": Decimal("0.20")},
        max_position_weight=Decimal("0.50"),
    )
    state = _make_valuation([("A", "EUR", Decimal("400")), ("B", "EUR", Decimal("100"))])
    amount = Decimal("500")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    # post_total = 500 + 500 = 1000. Max value per position = 500.
    # A already at 400, so max buy for A = 100.
    # Excess goes to B.
    a_trade = next(t for t in result.trades if t.ticker == "A")
    b_trade = next(t for t in result.trades if t.ticker == "B")

    # A's final value (400 + buy) should not greatly exceed 50% of 1000
    a_final_weight = (Decimal("400") + a_trade.buy_amount) / Decimal("1000")
    assert a_final_weight <= Decimal("0.501")  # soft clamp tolerance

    assert b_trade.buy_amount > Decimal("0")
    assert result.total_allocated + result.unallocated == amount


def test_max_weight_all_at_max() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.50"), "B": Decimal("0.50")},
        max_position_weight=Decimal("0.40"),
    )
    # Both at 45% each of post-contribution total (900/(900+200)=81.8%) — way over max
    state = _make_valuation([("A", "EUR", Decimal("450")), ("B", "EUR", Decimal("450"))])
    amount = Decimal("100")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    # post_total = 1000, max per position = 400, both already at 450 > 400
    assert result.trades == []
    assert result.unallocated == amount


# ---------------------------------------------------------------------------
# E. Validation errors
# ---------------------------------------------------------------------------


def test_validation_amount_zero_raises() -> None:
    policy = _make_policy(core_targets={"A": Decimal("1")})
    state = _make_valuation([])

    with pytest.raises(ValidationError) as exc_info:
        allocate_contribution(state, policy, Decimal("0"), "EUR", include_satellite=False)

    assert "positive" in exc_info.value.message.lower()


def test_validation_amount_negative_raises() -> None:
    policy = _make_policy(core_targets={"A": Decimal("1")})
    state = _make_valuation([])

    with pytest.raises(ValidationError) as exc_info:
        allocate_contribution(state, policy, Decimal("-100"), "EUR", include_satellite=False)

    assert "positive" in exc_info.value.message.lower()


def test_validation_currency_mismatch_raises() -> None:
    policy = _make_policy(core_targets={"A": Decimal("1")})
    state = _make_valuation([])

    with pytest.raises(ValidationError) as exc_info:
        allocate_contribution(state, policy, Decimal("100"), "USD", include_satellite=False)

    assert "USD" in exc_info.value.message


def test_validation_satellite_absent_raises() -> None:
    policy = _make_policy(core_targets={"A": Decimal("1")})
    state = _make_valuation([])

    with pytest.raises(ValidationError) as exc_info:
        allocate_contribution(state, policy, Decimal("100"), "EUR", include_satellite=True)

    assert "satellite" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# F. Edge cases and determinism
# ---------------------------------------------------------------------------


def test_empty_portfolio_allocates_proportionally() -> None:
    policy = _make_policy(core_targets={"A": Decimal("0.60"), "B": Decimal("0.30"), "C": Decimal("0.10")})
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    a = next(t for t in result.trades if t.ticker == "A")
    b = next(t for t in result.trades if t.ticker == "B")
    c = next(t for t in result.trades if t.ticker == "C")

    assert a.buy_amount == Decimal("600.00")
    assert b.buy_amount == Decimal("300.00")
    assert c.buy_amount == Decimal("100.00")


def test_deterministic_output() -> None:
    policy = _make_policy(core_targets={"X": Decimal("0.40"), "Y": Decimal("0.35"), "Z": Decimal("0.25")})
    state = _make_valuation([("X", "EUR", Decimal("100")), ("Y", "EUR", Decimal("200"))])
    amount = Decimal("700")

    result1 = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)
    result2 = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert result1 == result2


def test_no_positive_gaps_returns_empty() -> None:
    # With buy-only and targets summing to 1.0, it's hard to get zero positive gaps.
    # The max_position_weight clamp can eliminate all trades even when gaps exist.
    # This is tested by test_max_weight_all_at_max. Here we use min_trade_value
    # to force all trades below threshold on a tiny contribution with many tickers.
    policy = _make_policy(
        core_targets={
            "A": Decimal("0.25"),
            "B": Decimal("0.25"),
            "C": Decimal("0.25"),
            "D": Decimal("0.25"),
        },
        min_trade_value=Decimal("10"),
    )
    # Portfolio with 100k, contributing 1 EUR -> each ticker gets ~0.25 EUR, below min_trade=10
    state = _make_valuation(
        [
            ("A", "EUR", Decimal("25000")),
            ("B", "EUR", Decimal("25000")),
            ("C", "EUR", Decimal("25000")),
            ("D", "EUR", Decimal("25000")),
        ]
    )
    amount = Decimal("1")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert result.trades == []
    assert result.unallocated == amount


def test_single_ticker_gets_full_amount() -> None:
    policy = _make_policy(core_targets={"ONLY": Decimal("1")})
    state = _make_valuation([])
    amount = Decimal("999.99")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    assert len(result.trades) == 1
    assert result.trades[0].ticker == "ONLY"
    assert result.trades[0].buy_amount == Decimal("999.99")
    assert result.total_allocated == Decimal("999.99")
    assert result.unallocated == Decimal("0")


def test_trades_sorted_by_ticker() -> None:
    policy = _make_policy(
        core_targets={"ZZZ": Decimal("0.25"), "AAA": Decimal("0.25"), "MMM": Decimal("0.25"), "BBB": Decimal("0.25")}
    )
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    tickers = [t.ticker for t in result.trades]
    assert tickers == sorted(tickers)
    assert tickers == ["AAA", "BBB", "MMM", "ZZZ"]


def test_policy_hash_in_result() -> None:
    policy = _make_policy(core_targets={"A": Decimal("1")})
    state = _make_valuation([])

    result = allocate_contribution(state, policy, Decimal("100"), "EUR", include_satellite=False)

    assert result.policy_hash == "testhash123"


def test_renormalization_with_satellite() -> None:
    policy = _make_policy(
        core_targets={"A": Decimal("0.60"), "B": Decimal("0.40")},
        satellite_targets={"C": Decimal("0.70"), "D": Decimal("0.30")},
    )
    state = _make_valuation([])
    amount = Decimal("2000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=True)

    # Core sums to 1.0, satellite sums to 1.0, combined = 2.0
    # After renormalization: A=0.30, B=0.20, C=0.35, D=0.15
    a = next(t for t in result.trades if t.ticker == "A")
    b = next(t for t in result.trades if t.ticker == "B")
    c = next(t for t in result.trades if t.ticker == "C")
    d = next(t for t in result.trades if t.ticker == "D")

    assert a.target_weight == Decimal("0.60") / Decimal("2")  # 0.30
    assert b.target_weight == Decimal("0.40") / Decimal("2")  # 0.20
    assert c.target_weight == Decimal("0.70") / Decimal("2")  # 0.35
    assert d.target_weight == Decimal("0.30") / Decimal("2")  # 0.15

    # Empty portfolio -> allocation proportional to targets
    assert a.buy_amount == Decimal("600.00")
    assert b.buy_amount == Decimal("400.00")
    assert c.buy_amount == Decimal("700.00")
    assert d.buy_amount == Decimal("300.00")


def test_existing_portfolio_allocates_to_underweight() -> None:
    """Contribution should preferentially go to underweight positions."""
    policy = _make_policy(core_targets={"A": Decimal("0.50"), "B": Decimal("0.50")})
    # A is overweight, B is underweight
    state = _make_valuation([("A", "EUR", Decimal("800")), ("B", "EUR", Decimal("200"))])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    a_trade = next((t for t in result.trades if t.ticker == "A"), None)
    b_trade = next(t for t in result.trades if t.ticker == "B")

    # B should get more than A since B is more underweight
    if a_trade is not None:
        assert b_trade.buy_amount > a_trade.buy_amount
    assert result.total_allocated + result.unallocated == amount


def test_max_weight_redistributes_excess() -> None:
    """Excess from clamped positions flows to unclamped ones."""
    policy = _make_policy(
        core_targets={"A": Decimal("0.70"), "B": Decimal("0.30")},
        max_position_weight=Decimal("0.40"),
    )
    state = _make_valuation([])
    amount = Decimal("1000")

    result = allocate_contribution(state, policy, amount, "EUR", include_satellite=False)

    # post_total = 1000, max per position = 400
    # Without clamp: A=700, B=300. A clamped to 400, excess 300 goes to B.
    # B would get 300+300=600, but B also clamped to 400. Excess 200 unallocated.
    a = next(t for t in result.trades if t.ticker == "A")
    b = next(t for t in result.trades if t.ticker == "B")

    assert a.buy_amount <= Decimal("400.01")
    assert b.buy_amount <= Decimal("400.01")
    assert result.total_allocated + result.unallocated == amount


# ---------------------------------------------------------------------------
# G. Realistic scenarios with hand-calculated expected values
#
# Each test documents the full arithmetic trace so a human can verify
# the algorithm step-by-step with pen and paper.
# ---------------------------------------------------------------------------


def test_scenario_classic_3etf_first_contribution() -> None:
    """Classic 3-ETF portfolio, first contribution into empty portfolio.

    Policy: IWDA.AS=60%, EIMI.AS=25%, IUSN.AS=15%, min_trade=50
    State: empty (total=0)
    Contribution: 1000 EUR

    post_total = 0 + 1000 = 1000
    current_weights: all 0
    gaps: IWDA=0.60, EIMI=0.25, IUSN=0.15 (total=1.0)
    raw: IWDA=600, EIMI=250, IUSN=150
    No clamping (max=1.0). All above min_trade=50.
    """
    policy = _make_policy(
        core_targets={
            "IWDA.AS": Decimal("0.60"),
            "EIMI.AS": Decimal("0.25"),
            "IUSN.AS": Decimal("0.15"),
        },
        min_trade_value=Decimal("50"),
    )
    state = _make_valuation([])

    result = allocate_contribution(state, policy, Decimal("1000"), "EUR", include_satellite=False)

    iwda = next(t for t in result.trades if t.ticker == "IWDA.AS")
    eimi = next(t for t in result.trades if t.ticker == "EIMI.AS")
    iusn = next(t for t in result.trades if t.ticker == "IUSN.AS")

    assert iwda.buy_amount == Decimal("600.00")
    assert eimi.buy_amount == Decimal("250.00")
    assert iusn.buy_amount == Decimal("150.00")
    assert result.unallocated == Decimal("0")
    assert result.total_allocated == Decimal("1000.00")

    # Verify rationale fields
    assert iwda.current_weight == Decimal("0")
    assert iwda.target_weight == Decimal("0.60")
    assert iwda.gap == Decimal("0.60")


def test_scenario_drifted_portfolio_rebalancing() -> None:
    """Drifted portfolio where contribution fills the gaps exactly.

    Policy: A=50%, B=30%, C=20%
    State: A=6000, B=2000, C=2000 (total=10000)
    Contribution: 2000 EUR

    post_total = 12000
    current_weights: A=6000/12000=0.50, B=2000/12000=1/6, C=2000/12000=1/6
    gaps: A=0 (skip), B=0.30-1/6=2/15, C=0.20-1/6=1/30
    total_gap = 2/15 + 1/30 = 5/30 = 1/6
    raw: B = 2000*(2/15)/(1/6) = 2000*4/5 = 1600
         C = 2000*(1/30)/(1/6) = 2000*1/5 = 400

    Final weights: A=6000/12000=50%, B=3600/12000=30%, C=2400/12000=20% ✓
    """
    policy = _make_policy(
        core_targets={"A": Decimal("0.50"), "B": Decimal("0.30"), "C": Decimal("0.20")},
    )
    state = _make_valuation(
        [
            ("A", "EUR", Decimal("6000")),
            ("B", "EUR", Decimal("2000")),
            ("C", "EUR", Decimal("2000")),
        ]
    )

    result = allocate_contribution(state, policy, Decimal("2000"), "EUR", include_satellite=False)

    # A is at target weight -> no trade for A
    a_trade = next((t for t in result.trades if t.ticker == "A"), None)
    assert a_trade is None

    b = next(t for t in result.trades if t.ticker == "B")
    c = next(t for t in result.trades if t.ticker == "C")

    assert b.buy_amount == Decimal("1600.00")
    assert c.buy_amount == Decimal("400.00")
    assert result.total_allocated == Decimal("2000.00")
    assert result.unallocated == Decimal("0")

    # Verify final portfolio weights
    final_a = Decimal("6000") / Decimal("12000")
    final_b = (Decimal("2000") + b.buy_amount) / Decimal("12000")
    final_c = (Decimal("2000") + c.buy_amount) / Decimal("12000")
    assert final_a == Decimal("0.50")
    assert final_b == Decimal("0.30")
    assert final_c == Decimal("0.20")


def test_scenario_max_weight_clamp_exact() -> None:
    """Max weight clamp where both positions hit the cap exactly.

    Policy: A=70%, B=30%, max_weight=0.50
    State: empty (total=0)
    Contribution: 1000 EUR

    post_total = 1000
    gaps: A=0.70, B=0.30 (total=1.0)
    raw: A=700, B=300
    clamp iter 1: A max_buy=500, A clamped to 500, excess=200
      redistribute 200 to B (only eligible): B headroom=500-300=200, B gets 200 -> B=500
    clamp iter 2: excess=0, done

    Final: A=500/1000=50%, B=500/1000=50%
    """
    policy = _make_policy(
        core_targets={"A": Decimal("0.70"), "B": Decimal("0.30")},
        max_position_weight=Decimal("0.50"),
    )
    state = _make_valuation([])

    result = allocate_contribution(state, policy, Decimal("1000"), "EUR", include_satellite=False)

    a = next(t for t in result.trades if t.ticker == "A")
    b = next(t for t in result.trades if t.ticker == "B")

    assert a.buy_amount == Decimal("500.00")
    assert b.buy_amount == Decimal("500.00")
    assert result.total_allocated == Decimal("1000.00")
    assert result.unallocated == Decimal("0")


def test_scenario_min_trade_filtering() -> None:
    """Min-trade filter drops two small trades, redistributes to the big one.

    Policy: A=80%, B=15%, C=5%, min_trade=100
    State: empty (total=0)
    Contribution: 500 EUR

    post_total = 500
    gaps: A=0.80, B=0.15, C=0.05 (total=1.0)
    raw: A=400, B=75, C=25
    min_trade pass 1: below={B:75, C:25}, both dropped. Reclaimed=100.
      remaining={A:400}. A gets 400+100=500.
    min_trade pass 2: no below-threshold trades. Done.
    """
    policy = _make_policy(
        core_targets={"A": Decimal("0.80"), "B": Decimal("0.15"), "C": Decimal("0.05")},
        min_trade_value=Decimal("100"),
    )
    state = _make_valuation([])

    result = allocate_contribution(state, policy, Decimal("500"), "EUR", include_satellite=False)

    assert len(result.trades) == 1
    a = result.trades[0]
    assert a.ticker == "A"
    assert a.buy_amount == Decimal("500.00")
    assert result.total_allocated == Decimal("500.00")
    assert result.unallocated == Decimal("0")


def test_scenario_satellite_overweight_core() -> None:
    """Satellite gets all allocation when core tickers are overweight.

    Policy: core={X=60%, Y=40%}, satellite={Z=100%}
    State: X=2000, Y=1000, Z=0 (total=3000)
    Contribution: 1500 EUR

    Renormalized targets: total=2.0 -> X=0.30, Y=0.20, Z=0.50
    post_total = 4500
    current_weights: X=2000/4500=4/9≈0.444, Y=1000/4500=2/9≈0.222, Z=0
    gaps: X=0.30-4/9<0 (skip), Y=0.20-2/9<0 (skip), Z=0.50-0=0.50
    Only Z has positive gap. Z gets all 1500.
    """
    policy = _make_policy(
        core_targets={"X": Decimal("0.60"), "Y": Decimal("0.40")},
        satellite_targets={"Z": Decimal("1")},
    )
    state = _make_valuation(
        [
            ("X", "EUR", Decimal("2000")),
            ("Y", "EUR", Decimal("1000")),
            ("Z", "EUR", Decimal("0")),
        ]
    )

    result = allocate_contribution(state, policy, Decimal("1500"), "EUR", include_satellite=True)

    assert len(result.trades) == 1
    z = result.trades[0]
    assert z.ticker == "Z"
    assert z.buy_amount == Decimal("1500.00")
    assert result.total_allocated == Decimal("1500.00")
    assert result.unallocated == Decimal("0")


def test_scenario_combined_constraints() -> None:
    """Both max_weight and min_trade active, with an overweight position.

    Policy: A=60%, B=25%, C=15%, min_trade=50, max_weight=0.40
    State: A=3500, B=500, C=0 (total=4000)
    Contribution: 1000 EUR

    post_total = 5000, max per position = 2000
    current_weights: A=3500/5000=0.70, B=500/5000=0.10, C=0
    gaps: A=0.60-0.70<0 (skip), B=0.25-0.10=0.15, C=0.15-0=0.15
    total_gap = 0.30
    raw: B=1000*0.15/0.30=500, C=1000*0.15/0.30=500
    clamp: B headroom=2000-500=1500 (ok), C headroom=2000-0=2000 (ok)
    min_trade: B=500>50 ✓, C=500>50 ✓
    """
    policy = _make_policy(
        core_targets={"A": Decimal("0.60"), "B": Decimal("0.25"), "C": Decimal("0.15")},
        min_trade_value=Decimal("50"),
        max_position_weight=Decimal("0.40"),
    )
    state = _make_valuation(
        [
            ("A", "EUR", Decimal("3500")),
            ("B", "EUR", Decimal("500")),
            ("C", "EUR", Decimal("0")),
        ]
    )

    result = allocate_contribution(state, policy, Decimal("1000"), "EUR", include_satellite=False)

    # A is overweight -> no trade
    a_trade = next((t for t in result.trades if t.ticker == "A"), None)
    assert a_trade is None

    b = next(t for t in result.trades if t.ticker == "B")
    c = next(t for t in result.trades if t.ticker == "C")

    assert b.buy_amount == Decimal("500.00")
    assert c.buy_amount == Decimal("500.00")
    assert result.total_allocated == Decimal("1000.00")
    assert result.unallocated == Decimal("0")


def test_scenario_odd_cent_precision() -> None:
    """Odd-cent contribution amount to exercise Decimal quantization.

    Policy: A=60%, B=40%
    State: empty (total=0)
    Contribution: 1333.37 EUR

    post_total = 1333.37
    gaps: A=0.60, B=0.40 (total=1.0)
    raw: A = 1333.37 * 0.60 = 800.022
         B = 1333.37 * 0.40 = 533.348
    quantized (ROUND_HALF_EVEN): A=800.02, B=533.35
    total_allocated = 1333.37
    """
    policy = _make_policy(
        core_targets={"A": Decimal("0.60"), "B": Decimal("0.40")},
    )
    state = _make_valuation([])

    result = allocate_contribution(state, policy, Decimal("1333.37"), "EUR", include_satellite=False)

    a = next(t for t in result.trades if t.ticker == "A")
    b = next(t for t in result.trades if t.ticker == "B")

    assert a.buy_amount == Decimal("800.02")
    assert b.buy_amount == Decimal("533.35")
    assert result.total_allocated == Decimal("1333.37")
    assert result.unallocated == Decimal("0.00")
