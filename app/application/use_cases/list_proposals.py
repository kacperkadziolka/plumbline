from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import ProposalRepository


class ProposalSummary(BaseModel):
    proposal_id: int
    policy_id: int
    amount: Decimal
    currency: str
    created_at: datetime


class ListProposalsResult(BaseModel):
    proposals: list[ProposalSummary]
    count: int


async def list_proposals(
    session: AsyncSession,
    limit: int = 100,
) -> ListProposalsResult:
    """List stored proposals ordered by created_at descending.

    Note: Does not commit. Caller owns the transaction boundary.
    """
    repo = ProposalRepository(session)
    proposals = await repo.list_proposals(limit=limit)

    summaries = [
        ProposalSummary(
            proposal_id=p.id,
            policy_id=p.policy_id,
            amount=p.amount,
            currency=p.currency,
            created_at=p.created_at,
        )
        for p in proposals
    ]

    return ListProposalsResult(proposals=summaries, count=len(summaries))
