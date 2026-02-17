import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.save_backtest_run import SaveBacktestRunResult, save_backtest_run
from app.core.errors import DataMissingError
from app.domain.simulator import EquityCurveRow, SimulationMetrics, SimulationResult
from app.infrastructure.db.repositories import BacktestRunRepository, PolicyRepository

VALID_POLICY_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"
BACKTEST_YAML = (
    "start_date: 2024-01-01\nend_date: 2024-12-31\n"
    "contribution_schedule:\n  type: monthly\n  amount: 1000\n  currency: EUR\n"
)


def _make_simulation_result(
    *,
    cagr: Decimal | None = None,
    annualized_volatility: Decimal | None = None,
) -> SimulationResult:
    return SimulationResult(
        curve=[
            EquityCurveRow(
                date=date(2024, 1, 15),
                equity=Decimal("1000.00"),
                cash=Decimal("0.00"),
                positions_value=Decimal("1000.00"),
                drawdown=Decimal("0"),
                cumulative_costs=Decimal("5.00"),
                contribution_today=Decimal("1000.00"),
                cumulative_traded_value=Decimal("1000.00"),
            ),
            EquityCurveRow(
                date=date(2024, 2, 15),
                equity=Decimal("2050.00"),
                cash=Decimal("0.00"),
                positions_value=Decimal("2050.00"),
                drawdown=Decimal("0"),
                cumulative_costs=Decimal("10.00"),
                contribution_today=Decimal("1000.00"),
                cumulative_traded_value=Decimal("2000.00"),
            ),
        ],
        metrics=SimulationMetrics(
            total_return=Decimal("0.025"),
            cagr=cagr,
            max_drawdown=Decimal("0.01"),
            total_costs=Decimal("10.00"),
            total_contributions=Decimal("2000.00"),
            final_equity=Decimal("2050.00"),
            annualized_volatility=annualized_volatility,
            turnover=Decimal("1.31"),
        ),
        curve_hash="abc123curvehash",
        policy_hash="abc123policyhash",
    )


async def test_save_backtest_run_persists_and_returns_result(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "somehash")
    await session.flush()

    result = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash123",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    assert isinstance(result, SaveBacktestRunResult)
    assert result.policy_id == policy.id
    assert result.config_hash == "cfghash123"
    assert result.policy_hash == "abc123policyhash"
    assert result.curve_hash == "abc123curvehash"
    assert result.start_date == date(2024, 1, 1)
    assert result.end_date == date(2024, 12, 31)
    assert result.run_id is not None


async def test_save_backtest_run_raises_when_policy_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await save_backtest_run(
            policy_id=99999,
            backtest_yaml=BACKTEST_YAML,
            config_hash="cfghash",
            simulation_result=_make_simulation_result(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            session=session,
        )

    assert "Policy not found" in exc_info.value.message


async def test_save_backtest_run_stores_valid_json(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "somehash2")
    await session.flush()

    result = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash2",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    repo = BacktestRunRepository(session)
    run = await repo.get_by_id(result.run_id)
    assert run is not None

    metrics = json.loads(run.metrics_json)
    assert metrics["total_return"] == "0.025"
    assert metrics["total_costs"] == "10.00"
    assert metrics["final_equity"] == "2050.00"
    assert Decimal(metrics["turnover"]) == Decimal("1.31")

    curve = json.loads(run.curve_json)
    assert len(curve) == 2
    assert curve[0]["date"] == "2024-01-15"
    assert Decimal(curve[0]["equity"]) == Decimal("1000.00")
    assert Decimal(curve[1]["equity"]) == Decimal("2050.00")


async def test_save_backtest_run_round_trip(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "somehash3")
    await session.flush()

    sim = _make_simulation_result(cagr=Decimal("0.05"), annualized_volatility=Decimal("0.12"))
    result = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash3",
        simulation_result=sim,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    from app.application.use_cases.get_backtest_run import get_backtest_run

    fetched = await get_backtest_run(result.run_id, session)

    assert fetched.curve_hash == "abc123curvehash"
    assert fetched.policy_hash == "abc123policyhash"
    assert fetched.config_hash == "cfghash3"
    assert fetched.metrics.total_return == Decimal("0.025")
    assert fetched.metrics.cagr == Decimal("0.05")
    assert fetched.metrics.max_drawdown == Decimal("0.01")
    assert fetched.metrics.total_costs == Decimal("10.00")
    assert fetched.metrics.total_contributions == Decimal("2000.00")
    assert fetched.metrics.final_equity == Decimal("2050.00")
    assert fetched.metrics.annualized_volatility == Decimal("0.12")
    assert fetched.metrics.turnover == Decimal("1.31")

    assert len(fetched.curve) == 2
    assert fetched.curve[0].date == date(2024, 1, 15)
    assert fetched.curve[0].equity == Decimal("1000.00")
    assert fetched.curve[0].contribution_today == Decimal("1000.00")
    assert fetched.curve[1].date == date(2024, 2, 15)
    assert fetched.curve[1].equity == Decimal("2050.00")


async def test_save_backtest_run_with_none_metrics(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "somehash4")
    await session.flush()

    sim = _make_simulation_result(cagr=None, annualized_volatility=None)
    result = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash4",
        simulation_result=sim,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    from app.application.use_cases.get_backtest_run import get_backtest_run

    fetched = await get_backtest_run(result.run_id, session)
    assert fetched.metrics.cagr is None
    assert fetched.metrics.annualized_volatility is None


async def test_save_backtest_run_multiple_for_same_policy(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "somehash5")
    await session.flush()

    r1 = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash5a",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 30),
        session=session,
    )
    r2 = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash5b",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    assert r1.run_id != r2.run_id
    assert r1.policy_id == r2.policy_id == policy.id
    assert r1.end_date == date(2024, 6, 30)
    assert r2.end_date == date(2024, 12, 31)
