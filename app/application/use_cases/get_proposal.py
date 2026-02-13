import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.repositories import ProposalRepository


class TradeRow(BaseModel):
    ticker: str
    buy_amount: Decimal
    current_weight: Decimal
    target_weight: Decimal
    gap: Decimal


class GetProposalResult(BaseModel):
    proposal_id: int
    policy_id: int
    amount: Decimal
    currency: str
    created_at: datetime
    total_allocated: Decimal
    unallocated: Decimal
    policy_hash: str
    trades: list[TradeRow]


async def get_proposal(
    proposal_id: int,
    session: AsyncSession,
) -> GetProposalResult:
    """Retrieve a proposal by ID, deserializing its result_json.

    Raises:
        DataMissingError: If no proposal with this ID exists.
    """
    repo = ProposalRepository(session)
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise DataMissingError(
            message="Proposal not found",
            details=f"No proposal with id={proposal_id}",
        )

    data = json.loads(proposal.result_json)
    trades = [
        TradeRow(
            ticker=t["ticker"],
            buy_amount=Decimal(t["buy_amount"]),
            current_weight=Decimal(t["current_weight"]),
            target_weight=Decimal(t["target_weight"]),
            gap=Decimal(t["gap"]),
        )
        for t in data["trades"]
    ]

    return GetProposalResult(
        proposal_id=proposal.id,
        policy_id=proposal.policy_id,
        amount=proposal.amount,
        currency=proposal.currency,
        created_at=proposal.created_at,
        total_allocated=Decimal(data["total_allocated"]),
        unallocated=Decimal(data["unallocated"]),
        policy_hash=data["policy_hash"],
        trades=trades,
    )
