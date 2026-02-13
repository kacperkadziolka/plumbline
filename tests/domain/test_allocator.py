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
