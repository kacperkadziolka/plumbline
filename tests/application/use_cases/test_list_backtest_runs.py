from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.list_backtest_runs import ListBacktestRunsResult, list_backtest_runs
from app.application.use_cases.save_backtest_run import save_backtest_run
from app.domain.simulator import EquityCurveRow, SimulationMetrics, SimulationResult
from app.infrastructure.db.repositories import PolicyRepository

VALID_POLICY_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"
BACKTEST_YAML = "start_date: 2024-01-01\nend_date: 2024-12-31\n"


def _make_simulation_result() -> SimulationResult:
    return SimulationResult(
        curve=[
            EquityCurveRow(
                date=date(2024, 1, 15),
                equity=Decimal("1000"),
                cash=Decimal("0"),
                positions_value=Decimal("1000"),
                drawdown=Decimal("0"),
                cumulative_costs=Decimal("0"),
                contribution_today=Decimal("1000"),
                cumulative_traded_value=Decimal("1000"),
            ),
        ],
        metrics=SimulationMetrics(
            total_return=Decimal("0"),
            cagr=None,
            max_drawdown=Decimal("0"),
            total_costs=Decimal("0"),
            total_contributions=Decimal("1000"),
            final_equity=Decimal("1000"),
            annualized_volatility=None,
            turnover=Decimal("1"),
        ),
        curve_hash="curvehash",
        policy_hash="policyhash",
    )


async def test_list_backtest_runs_returns_summaries(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "hash1")
    await session.flush()

    await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfg1",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 30),
        session=session,
    )
    await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfg2",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    result = await list_backtest_runs(session)

    assert isinstance(result, ListBacktestRunsResult)
    assert result.count == 2
    assert len(result.runs) == 2
    # Newest first
    assert result.runs[0].end_date == date(2024, 12, 31)
    assert result.runs[1].end_date == date(2024, 6, 30)


async def test_list_backtest_runs_filters_by_policy(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    p1 = await policy_repo.save("policy1", VALID_POLICY_YAML, "hash_a")
    p2 = await policy_repo.save("policy2", VALID_POLICY_YAML + "\n", "hash_b")
    await session.flush()

    await save_backtest_run(
        policy_id=p1.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfg_p1",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await save_backtest_run(
        policy_id=p2.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfg_p2",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    result = await list_backtest_runs(session, policy_id=p1.id)

    assert result.count == 1
    assert result.runs[0].policy_id == p1.id


async def test_list_backtest_runs_returns_empty_when_none(session: AsyncSession) -> None:
    result = await list_backtest_runs(session)

    assert result.count == 0
    assert result.runs == []


async def test_list_backtest_runs_respects_limit(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "hash_limit")
    await session.flush()

    for i in range(5):
        await save_backtest_run(
            policy_id=policy.id,
            backtest_yaml=BACKTEST_YAML,
            config_hash=f"cfg_limit_{i}",
            simulation_result=_make_simulation_result(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            session=session,
        )
    await session.commit()

    result = await list_backtest_runs(session, limit=2)

    assert result.count == 2
    assert len(result.runs) == 2
