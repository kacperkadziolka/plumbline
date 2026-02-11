import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.save_policy import SavePolicyResult, save_policy
from app.core.errors import ValidationError
from app.infrastructure.db.repositories import PolicyRepository

VALID_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
"""


async def test_save_policy_persists_valid_yaml(session: AsyncSession) -> None:
    result = await save_policy("test-policy", VALID_YAML, session)
    await session.commit()

    assert isinstance(result, SavePolicyResult)
    assert result.name == "test-policy"
    assert result.already_existed is False
    assert len(result.policy_hash) == 64  # SHA-256 hex

    # Verify persisted in DB
    repo = PolicyRepository(session)
    found = await repo.get_by_hash(result.policy_hash)
    assert found is not None
    assert found.name == "test-policy"


async def test_save_policy_returns_existing_on_duplicate_yaml(session: AsyncSession) -> None:
    result1 = await save_policy("first-name", VALID_YAML, session)
    await session.commit()

    result2 = await save_policy("second-name", VALID_YAML, session)
    await session.commit()

    assert result1.policy_id == result2.policy_id
    assert result2.already_existed is True
    assert result2.name == "first-name"  # Original name preserved


async def test_save_policy_raises_validation_error_for_invalid_yaml(session: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await save_policy("bad-policy", "not: valid: yaml: {", session)


async def test_save_policy_raises_validation_error_for_empty_yaml(session: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await save_policy("empty", "", session)


async def test_save_policy_hash_matches_domain_computation(session: AsyncSession) -> None:
    result = await save_policy("test", VALID_YAML, session)
    await session.commit()

    expected_hash = hashlib.sha256(VALID_YAML.strip().encode("utf-8")).hexdigest()
    assert result.policy_hash == expected_hash
