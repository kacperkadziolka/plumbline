from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ValidationError
from app.domain.policy import PolicyConfig
from app.domain.valuation import PortfolioValuation

_QUANTIZE_2DP = Decimal("0.01")
_RESIDUAL_TOLERANCE = Decimal("0.01")
_MAX_CLAMP_ITERATIONS = 10


@dataclass(frozen=True)
class TradeProposal:
    ticker: str
    buy_amount: Decimal
    current_weight: Decimal
    target_weight: Decimal
    gap: Decimal


@dataclass(frozen=True)
class AllocationResult:
    trades: list[TradeProposal]
    total_allocated: Decimal
    unallocated: Decimal
    policy_hash: str


def _build_targets(policy: PolicyConfig, include_satellite: bool) -> dict[str, Decimal]:
    """Build combined target weight map from selected buckets.

    When include_satellite is True, both bucket target sets are merged and
    renormalized to sum to 1.0. Since each bucket independently sums to 1.0,
    this gives each bucket equal (50/50) weight in the combined allocation.
    """
    targets = dict(sorted(policy.buckets.core.targets.items()))

    if include_satellite and policy.buckets.satellite is not None:
        for ticker, weight in policy.buckets.satellite.targets.items():
            if ticker in targets:
                raise ValidationError(message=f"Ticker '{ticker}' appears in both core and satellite buckets")
            targets[ticker] = weight
        total_weight = sum(targets.values())
        targets = {t: w / total_weight for t, w in sorted(targets.items())}

    return targets


def _apply_max_position_weight(
    allocations: dict[str, Decimal],
    current_values: dict[str, Decimal],
    post_total: Decimal,
    max_weight: Decimal,
    gaps: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Soft-clamp allocations so no position exceeds max_position_weight.

    Iteratively clamps and redistributes excess. Due to Decimal rounding and
    cascading redistribution, the final weight may exceed max_position_weight
    by a small epsilon (documented tolerance: ~0.1% of portfolio value).
    """
    clamped = dict(allocations)

    for _ in range(_MAX_CLAMP_ITERATIONS):
        excess = Decimal("0")
        for ticker in sorted(clamped.keys()):
            current_value = current_values.get(ticker, Decimal("0"))
            max_buy = max_weight * post_total - current_value
            if max_buy < Decimal("0"):
                max_buy = Decimal("0")
            if clamped[ticker] > max_buy:
                excess += clamped[ticker] - max_buy
                clamped[ticker] = max_buy

        if excess <= _RESIDUAL_TOLERANCE:
            break

        eligible: dict[str, Decimal] = {}
        for ticker in sorted(clamped.keys()):
            current_value = current_values.get(ticker, Decimal("0"))
            headroom = max_weight * post_total - current_value - clamped[ticker]
            if headroom > _RESIDUAL_TOLERANCE:
                eligible[ticker] = gaps[ticker]

        if not eligible:
            break

        eligible_gap_total = sum(eligible.values())
        distributed = Decimal("0")
        for ticker in sorted(eligible.keys()):
            extra = excess * eligible[ticker] / eligible_gap_total
            current_value = current_values.get(ticker, Decimal("0"))
            headroom = max_weight * post_total - current_value - clamped[ticker]
            add = min(extra, headroom)
            clamped[ticker] += add
            distributed += add
        excess -= distributed

    return clamped


def _apply_min_trade_value(
    allocations: dict[str, Decimal],
    min_trade: Decimal,
) -> dict[str, Decimal]:
    """Drop trades below min_trade_value, redistributing to remaining trades."""
    if min_trade <= Decimal("0"):
        return allocations

    result = dict(allocations)
    changed = True
    while changed:
        changed = False
        below = {t: a for t, a in result.items() if Decimal("0") < a < min_trade}
        if below:
            changed = True
            reclaimed = sum(below.values())
            for ticker in below:
                del result[ticker]
            remaining = {t: a for t, a in result.items() if a > Decimal("0")}
            if remaining:
                remaining_total = sum(remaining.values())
                for ticker in sorted(remaining.keys()):
                    result[ticker] += reclaimed * remaining[ticker] / remaining_total
            # If no remaining trades, reclaimed is lost (becomes unallocated)

    return result


def allocate_contribution(
    state: PortfolioValuation,
    policy: PolicyConfig,
    amount: Decimal,
    currency: str,
    include_satellite: bool,
) -> AllocationResult:
    """Allocate a cash contribution to reduce drift from policy targets.

    Produces buy-only trades proportional to the gap between current and target
    weights. Uses post-contribution total as denominator so target weights
    reflect the desired final portfolio state.

    Args:
        state: Current portfolio valuation (positions + total value).
        policy: Validated policy configuration with targets and constraints.
        amount: Contribution amount in base currency (must be positive).
        currency: Currency of the contribution (must match policy.base_currency).
        include_satellite: Whether to include satellite bucket tickers.

    Returns:
        AllocationResult with deterministically ordered trades.

    Raises:
        ValidationError: Invalid inputs (negative amount, currency mismatch, etc.).
    """
    # --- 1. Input validation ---
    if amount <= Decimal("0"):
        raise ValidationError(message="Contribution amount must be positive", details=f"Got {amount}")

    if currency.upper() != policy.base_currency:
        raise ValidationError(
            message=f"Currency '{currency}' does not match policy base currency '{policy.base_currency}'"
        )

    if include_satellite and policy.buckets.satellite is None:
        raise ValidationError(message="include_satellite=True but policy has no satellite bucket")

    # --- 2. Build target map ---
    targets = _build_targets(policy, include_satellite)

    # --- 3. Compute current weights (post-contribution denominator) ---
    post_total = state.total_value + amount

    current_values: dict[str, Decimal] = {}
    for pos in state.positions:
        current_values[pos.ticker] = pos.value_base

    current_weights: dict[str, Decimal] = {}
    for ticker in sorted(targets.keys()):
        value = current_values.get(ticker, Decimal("0"))
        current_weights[ticker] = value / post_total if post_total > Decimal("0") else Decimal("0")

    # --- 4. Compute gaps (positive only) ---
    gaps: dict[str, Decimal] = {}
    for ticker in sorted(targets.keys()):
        gap = targets[ticker] - current_weights[ticker]
        if gap > Decimal("0"):
            gaps[ticker] = gap

    if not gaps:
        return AllocationResult(
            trades=[],
            total_allocated=Decimal("0"),
            unallocated=amount,
            policy_hash=policy.policy_hash,
        )

    # --- 5. Proportional allocation ---
    total_gap = sum(gaps.values())
    raw_allocations: dict[str, Decimal] = {}
    for ticker in sorted(gaps.keys()):
        raw_allocations[ticker] = amount * gaps[ticker] / total_gap

    # --- 6. Apply max_position_weight (soft clamp) ---
    clamped = _apply_max_position_weight(
        raw_allocations, current_values, post_total, policy.constraints.max_position_weight, gaps
    )

    # --- 7. Apply min_trade_value ---
    filtered = _apply_min_trade_value(clamped, policy.constraints.min_trade_value)

    # --- 8. Quantize and build result ---
    trades: list[TradeProposal] = []
    for ticker in sorted(filtered.keys()):
        buy = filtered[ticker].quantize(_QUANTIZE_2DP)
        if buy > Decimal("0"):
            trades.append(
                TradeProposal(
                    ticker=ticker,
                    buy_amount=buy,
                    current_weight=current_weights[ticker],
                    target_weight=targets[ticker],
                    gap=gaps.get(ticker, Decimal("0")),
                )
            )

    total_allocated = sum((t.buy_amount for t in trades), Decimal("0"))
    unallocated = amount - total_allocated

    return AllocationResult(
        trades=trades,
        total_allocated=total_allocated,
        unallocated=unallocated,
        policy_hash=policy.policy_hash,
    )
