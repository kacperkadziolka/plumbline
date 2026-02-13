from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.export_proposal_csv import export_proposal_csv
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


async def test_export_csv_contains_header_and_trades(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash1")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    csv_text = await export_proposal_csv(saved.proposal_id, session)

    lines = csv_text.strip().split("\n")

    # Comment header lines
    comment_lines = [line for line in lines if line.startswith("#")]
    assert len(comment_lines) == 8

    # CSV header row
    data_lines = [line for line in lines if not line.startswith("#")]
    assert data_lines[0] == "ticker,buy_amount,current_weight,target_weight,gap"

    # Trade rows
    assert len(data_lines) == 3  # header + 2 trades


async def test_export_csv_metadata_in_comments(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash2")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    csv_text = await export_proposal_csv(saved.proposal_id, session)

    assert f"# proposal_id: {saved.proposal_id}" in csv_text
    assert f"# policy_id: {policy.id}" in csv_text
    assert "# policy_hash: abc123def456" in csv_text
    assert "# amount: 1000.00" in csv_text
    assert "# currency: EUR" in csv_text
    assert "# total_allocated: 1000.00" in csv_text
    assert "# unallocated: 0.00" in csv_text


async def test_export_csv_raises_when_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError):
        await export_proposal_csv(99999, session)
