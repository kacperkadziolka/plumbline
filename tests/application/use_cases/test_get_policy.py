import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.get_policy import GetPolicyResult, get_policy
from app.application.use_cases.save_policy import save_policy
from app.core.errors import DataMissingError

VALID_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
"""


async def test_get_policy_returns_yaml_text(session: AsyncSession) -> None:
    saved = await save_policy("test", VALID_YAML, session)
    await session.commit()

    result = await get_policy(saved.policy_id, session)
    assert isinstance(result, GetPolicyResult)
    assert result.yaml_text == VALID_YAML.strip()
    assert result.name == "test"
    assert result.policy_hash == saved.policy_hash
    assert result.created_at == saved.created_at


async def test_get_policy_raises_for_nonexistent_id(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError):
        await get_policy(99999, session)
