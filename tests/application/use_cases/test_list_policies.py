from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.list_policies import ListPoliciesResult, list_policies
from app.application.use_cases.save_policy import save_policy

YAML_V1 = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
"""

YAML_V2 = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.50
      EIMI.AS: 0.30
      IUSN.AS: 0.20
"""


async def test_list_policies_returns_all(session: AsyncSession) -> None:
    await save_policy("alpha", YAML_V1, session)
    await save_policy("beta", YAML_V2, session)
    await session.commit()

    result = await list_policies(session)
    assert isinstance(result, ListPoliciesResult)
    assert result.count == 2


async def test_list_policies_filters_by_name(session: AsyncSession) -> None:
    await save_policy("alpha", YAML_V1, session)
    await save_policy("beta", YAML_V2, session)
    await session.commit()

    result = await list_policies(session, name="alpha")
    assert result.count == 1
    assert result.policies[0].name == "alpha"


async def test_list_policies_returns_empty_when_none_exist(session: AsyncSession) -> None:
    result = await list_policies(session)
    assert result.count == 0
    assert result.policies == []


async def test_list_policies_summary_excludes_yaml_text(session: AsyncSession) -> None:
    await save_policy("test", YAML_V1, session)
    await session.commit()

    result = await list_policies(session)
    summary = result.policies[0]
    assert not hasattr(summary, "yaml_text")
