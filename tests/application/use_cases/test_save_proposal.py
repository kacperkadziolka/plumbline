import json
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.save_proposal import SaveProposalResult, save_proposal
from app.core.errors import DataMissingError
from app.domain.allocator import AllocationResult, TradeProposal
from app.infrastructure.db.repositories import PolicyRepository, ProposalRepository

VALID_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"


def _make_allocation_result() -> AllocationResult:
    return AllocationResult(
        trades=[
            TradeProposal(
                ticker="IWDA.AS",
                buy_amount=Decimal("600.00"),
                current_weight=Decimal("0"),
                target_weight=Decimal("0.60"),
                gap=Decimal("0.60"),
            ),
            TradeProposal(
                ticker="EIMI.AS",
                buy_amount=Decimal("400.00"),
                current_weight=Decimal("0"),
                target_weight=Decimal("0.40"),
                gap=Decimal("0.40"),
            ),
        ],
        total_allocated=Decimal("1000.00"),
        unallocated=Decimal("0.00"),
        policy_hash="abc123def456",
    )


async def test_save_proposal_persists_and_returns_result(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "somehash")
    await session.flush()

    result = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    assert isinstance(result, SaveProposalResult)
    assert result.policy_id == policy.id
    assert result.amount == Decimal("1000.00")
    assert result.currency == "EUR"
    assert result.proposal_id is not None


async def test_save_proposal_raises_when_policy_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await save_proposal(99999, Decimal("1000.00"), "EUR", _make_allocation_result(), session)

    assert "Policy not found" in exc_info.value.message


async def test_save_proposal_stores_valid_json(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "somehash2")
    await session.flush()

    result = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    proposal_repo = ProposalRepository(session)
    proposal = await proposal_repo.get_by_id(result.proposal_id)
    assert proposal is not None

    data = json.loads(proposal.result_json)
    assert len(data["trades"]) == 2
    assert data["total_allocated"] == "1000.00"
    assert data["unallocated"] == "0.00"
    assert data["policy_hash"] == "abc123def456"

    # Verify Decimal precision preserved as strings
    trade = data["trades"][0]
    assert Decimal(trade["buy_amount"]) == Decimal("600.00")


async def test_save_proposal_with_empty_trades(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "somehash3")
    await session.flush()

    empty_result = AllocationResult(
        trades=[],
        total_allocated=Decimal("0"),
        unallocated=Decimal("1000.00"),
        policy_hash="empty_hash",
    )

    result = await save_proposal(policy.id, Decimal("1000.00"), "EUR", empty_result, session)
    await session.commit()

    # Round-trip: verify get_proposal deserializes empty trades correctly
    from app.application.use_cases.get_proposal import get_proposal

    fetched = await get_proposal(result.proposal_id, session)
    assert fetched.trades == []
    assert fetched.total_allocated == Decimal("0")
    assert fetched.unallocated == Decimal("1000.00")


async def test_save_proposal_multiple_for_same_policy(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "somehash4")
    await session.flush()

    r1 = await save_proposal(policy.id, Decimal("500.00"), "EUR", _make_allocation_result(), session)
    r2 = await save_proposal(policy.id, Decimal("1500.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    assert r1.proposal_id != r2.proposal_id
    assert r1.policy_id == r2.policy_id == policy.id
    assert r1.amount == Decimal("500.00")
    assert r2.amount == Decimal("1500.00")
