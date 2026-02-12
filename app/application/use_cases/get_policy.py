from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.repositories import PolicyRepository


class GetPolicyResult(BaseModel):
    policy_id: int
    name: str
    yaml_text: str
    policy_hash: str
    created_at: datetime


async def get_policy(
    policy_id: int,
    session: AsyncSession,
) -> GetPolicyResult:
    """Retrieve a single policy by ID, including its yaml_text.

    Raises:
        DataMissingError: If no policy with this ID exists.
    """
    repo = PolicyRepository(session)
    policy = await repo.get_by_id(policy_id)
    if policy is None:
        raise DataMissingError(
            message="Policy not found",
            details=f"No policy with id={policy_id}",
        )

    return GetPolicyResult(
        policy_id=policy.id,
        name=policy.name,
        yaml_text=policy.yaml_text,
        policy_hash=policy.hash,
        created_at=policy.created_at,
    )
