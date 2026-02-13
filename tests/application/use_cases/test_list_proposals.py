from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.list_proposals import ListProposalsResult, list_proposals
from app.application.use_cases.save_proposal import save_proposal
from app.domain.allocator import AllocationResult, TradeProposal
from app.infrastructure.db.repositories import PolicyRepository

VALID_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 1.0\n"


def _make_allocation_result(amount: Decimal) -> AllocationResult:
    return AllocationResult(
        trades=[
            TradeProposal(
                ticker="IWDA.AS",
                buy_amount=amount,
                current_weight=Decimal("0"),
                target_weight=Decimal("1.0"),
                gap=Decimal("1.0"),
            ),
        ],
        total_allocated=amount,
        unallocated=Decimal("0"),
        policy_hash="hash",
    )


async def test_list_proposals_returns_all(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash1")
    await session.flush()

    await save_proposal(policy.id, Decimal("100"), "EUR", _make_allocation_result(Decimal("100")), session)
    await save_proposal(policy.id, Decimal("200"), "EUR", _make_allocation_result(Decimal("200")), session)
    await session.commit()

    result = await list_proposals(session)

    assert isinstance(result, ListProposalsResult)
    assert result.count == 2
    assert len(result.proposals) == 2


async def test_list_proposals_returns_empty_when_none_exist(session: AsyncSession) -> None:
    result = await list_proposals(session)

    assert result.count == 0
    assert result.proposals == []


async def test_list_proposals_ordered_newest_first(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash2")
    await session.flush()

    await save_proposal(policy.id, Decimal("100"), "EUR", _make_allocation_result(Decimal("100")), session)
    await save_proposal(policy.id, Decimal("200"), "EUR", _make_allocation_result(Decimal("200")), session)
    await session.commit()

    result = await list_proposals(session)

    assert result.count == 2
    # Newest (200) should come first
    amounts = [p.amount for p in result.proposals]
    assert amounts == [Decimal("200"), Decimal("100")]
