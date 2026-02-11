from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import PolicyRepository


class PolicySummary(BaseModel):
    policy_id: int
    name: str
    policy_hash: str
    created_at: datetime


class ListPoliciesResult(BaseModel):
    policies: list[PolicySummary]
    count: int


async def list_policies(
    session: AsyncSession,
    name: str | None = None,
    limit: int = 100,
) -> ListPoliciesResult:
    """List stored policy versions, optionally filtered by name.

    Note: Does not commit. Caller owns the transaction boundary.
    """
    repo = PolicyRepository(session)
    policies = await repo.list_versions(name=name, limit=limit)

    summaries = [
        PolicySummary(
            policy_id=p.id,
            name=p.name,
            policy_hash=p.hash,
            created_at=p.created_at,
        )
        for p in policies
    ]

    return ListPoliciesResult(policies=summaries, count=len(summaries))
