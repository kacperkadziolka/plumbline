from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.get_proposal import GetProposalResult, get_proposal
from app.application.use_cases.save_proposal import save_proposal
from app.core.errors import DataMissingError
from app.domain.allocator import AllocationResult, TradeProposal
from app.infrastructure.db.repositories import PolicyRepository

VALID_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"


def _make_allocation_result() -> AllocationResult:
    return AllocationResult(
        trades=[
            TradeProposal(
                ticker="EIMI.AS",
                buy_amount=Decimal("400.00"),
                current_weight=Decimal("0.10"),
                target_weight=Decimal("0.40"),
                gap=Decimal("0.30"),
            ),
            TradeProposal(
                ticker="IWDA.AS",
                buy_amount=Decimal("600.00"),
                current_weight=Decimal("0.20"),
                target_weight=Decimal("0.60"),
                gap=Decimal("0.40"),
            ),
        ],
        total_allocated=Decimal("1000.00"),
        unallocated=Decimal("0.00"),
        policy_hash="abc123def456",
    )


async def test_get_proposal_returns_deserialized_result(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash1")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    result = await get_proposal(saved.proposal_id, session)

    assert isinstance(result, GetProposalResult)
    assert result.proposal_id == saved.proposal_id
    assert result.policy_id == policy.id
    assert result.amount == Decimal("1000.00")
    assert result.currency == "EUR"
    assert result.total_allocated == Decimal("1000.00")
    assert result.unallocated == Decimal("0.00")
    assert result.policy_hash == "abc123def456"
    assert len(result.trades) == 2

    tickers = [t.ticker for t in result.trades]
    assert "EIMI.AS" in tickers
    assert "IWDA.AS" in tickers


async def test_get_proposal_raises_when_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await get_proposal(99999, session)

    assert "Proposal not found" in exc_info.value.message


async def test_get_proposal_decimal_precision_preserved(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash2")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    result = await get_proposal(saved.proposal_id, session)

    eimi = next(t for t in result.trades if t.ticker == "EIMI.AS")
    assert eimi.buy_amount == Decimal("400.00")
    assert eimi.current_weight == Decimal("0.10")
    assert eimi.target_weight == Decimal("0.40")
    assert eimi.gap == Decimal("0.30")
