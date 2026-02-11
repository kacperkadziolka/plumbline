from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import parse_policy_yaml
from app.infrastructure.db.repositories import PolicyRepository


class SavePolicyResult(BaseModel):
    policy_id: int
    name: str
    policy_hash: str
    created_at: datetime
    already_existed: bool


async def save_policy(
    name: str,
    yaml_text: str,
    session: AsyncSession,
) -> SavePolicyResult:
    """Validate and persist a policy version.

    Orchestrates:
    1. Validate YAML via domain parse_policy_yaml (raises ValidationError on invalid)
    2. Check for duplicate hash (idempotent save)
    3. Persist via PolicyRepository

    Note: Does not commit. Caller owns the transaction boundary.

    Raises:
        ValidationError: If YAML is invalid or policy validation fails.
    """
    config = parse_policy_yaml(yaml_text)

    repo = PolicyRepository(session)
    existing = await repo.get_by_hash(config.policy_hash)
    if existing is not None:
        return SavePolicyResult(
            policy_id=existing.id,
            name=existing.name,
            policy_hash=existing.hash,
            created_at=existing.created_at,
            already_existed=True,
        )

    policy = await repo.save(name, yaml_text.strip(), config.policy_hash)

    return SavePolicyResult(
        policy_id=policy.id,
        name=policy.name,
        policy_hash=policy.hash,
        created_at=policy.created_at,
        already_existed=False,
    )
