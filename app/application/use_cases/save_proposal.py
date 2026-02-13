import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.domain.allocator import AllocationResult
from app.infrastructure.db.repositories import PolicyRepository, ProposalRepository


class SaveProposalResult(BaseModel):
    proposal_id: int
    policy_id: int
    amount: Decimal
    currency: str
    created_at: datetime


def _serialize_allocation_result(result: AllocationResult) -> str:
    """Serialize AllocationResult to a JSON string for storage."""
    return json.dumps(
        {
            "trades": [
                {
                    "ticker": t.ticker,
                    "buy_amount": str(t.buy_amount),
                    "current_weight": str(t.current_weight),
                    "target_weight": str(t.target_weight),
                    "gap": str(t.gap),
                }
                for t in result.trades
            ],
            "total_allocated": str(result.total_allocated),
            "unallocated": str(result.unallocated),
            "policy_hash": result.policy_hash,
        },
    )


async def save_proposal(
    policy_id: int,
    amount: Decimal,
    currency: str,
    allocation_result: AllocationResult,
    session: AsyncSession,
) -> SaveProposalResult:
    """Persist a proposal (allocation result) to the database.

    Validates that the referenced policy exists, serializes the AllocationResult
    to JSON, and saves via ProposalRepository.

    Note: Does not commit. Caller owns the transaction boundary.

    Raises:
        DataMissingError: If no policy with the given ID exists.
    """
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.get_by_id(policy_id)
    if policy is None:
        raise DataMissingError(
            message="Policy not found",
            details=f"No policy with id={policy_id}",
        )

    result_json = _serialize_allocation_result(allocation_result)

    proposal_repo = ProposalRepository(session)
    proposal = await proposal_repo.save(policy_id, amount, currency, result_json)

    return SaveProposalResult(
        proposal_id=proposal.id,
        policy_id=proposal.policy_id,
        amount=proposal.amount,
        currency=proposal.currency,
        created_at=proposal.created_at,
    )
