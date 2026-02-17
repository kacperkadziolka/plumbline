from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.get_backtest_run import GetBacktestRunResult, get_backtest_run
from app.application.use_cases.save_backtest_run import save_backtest_run
from app.core.errors import DataMissingError
from app.domain.simulator import EquityCurveRow, SimulationMetrics, SimulationResult
from app.infrastructure.db.repositories import PolicyRepository

VALID_POLICY_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"
BACKTEST_YAML = "start_date: 2024-01-01\nend_date: 2024-12-31\n"


def _make_simulation_result() -> SimulationResult:
    return SimulationResult(
        curve=[
            EquityCurveRow(
                date=date(2024, 1, 15),
                equity=Decimal("1000.00"),
                cash=Decimal("50.00"),
                positions_value=Decimal("950.00"),
                drawdown=Decimal("0"),
                cumulative_costs=Decimal("5.00"),
                contribution_today=Decimal("1000.00"),
                cumulative_traded_value=Decimal("950.00"),
            ),
        ],
        metrics=SimulationMetrics(
            total_return=Decimal("0"),
            cagr=Decimal("0.08"),
            max_drawdown=Decimal("0.05"),
            total_costs=Decimal("5.00"),
            total_contributions=Decimal("1000.00"),
            final_equity=Decimal("1000.00"),
            annualized_volatility=Decimal("0.15"),
            turnover=Decimal("0.95"),
        ),
        curve_hash="curvehash_abc",
        policy_hash="policyhash_abc",
    )


async def test_get_backtest_run_returns_deserialized_result(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "hash1")
    await session.flush()

    saved = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfghash1",
        simulation_result=_make_simulation_result(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    fetched = await get_backtest_run(saved.run_id, session)

    assert isinstance(fetched, GetBacktestRunResult)
    assert fetched.run_id == saved.run_id
    assert fetched.policy_id == policy.id
    assert fetched.backtest_yaml == BACKTEST_YAML
    assert fetched.config_hash == "cfghash1"
    assert fetched.policy_hash == "policyhash_abc"
    assert fetched.curve_hash == "curvehash_abc"
    assert fetched.start_date == date(2024, 1, 1)
    assert fetched.end_date == date(2024, 12, 31)

    assert fetched.metrics.total_return == Decimal("0")
    assert fetched.metrics.cagr == Decimal("0.08")
    assert fetched.metrics.max_drawdown == Decimal("0.05")
    assert fetched.metrics.total_costs == Decimal("5.00")
    assert fetched.metrics.total_contributions == Decimal("1000.00")
    assert fetched.metrics.final_equity == Decimal("1000.00")
    assert fetched.metrics.annualized_volatility == Decimal("0.15")
    assert fetched.metrics.turnover == Decimal("0.95")

    assert len(fetched.curve) == 1
    row = fetched.curve[0]
    assert row.date == date(2024, 1, 15)
    assert row.equity == Decimal("1000.00")
    assert row.cash == Decimal("50.00")
    assert row.positions_value == Decimal("950.00")
    assert row.drawdown == Decimal("0")
    assert row.cumulative_costs == Decimal("5.00")
    assert row.contribution_today == Decimal("1000.00")
    assert row.cumulative_traded_value == Decimal("950.00")


async def test_get_backtest_run_raises_when_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await get_backtest_run(99999, session)

    assert "Backtest run not found" in exc_info.value.message


async def test_get_backtest_run_preserves_decimal_precision(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_POLICY_YAML, "hash2")
    await session.flush()

    precise_result = SimulationResult(
        curve=[
            EquityCurveRow(
                date=date(2024, 3, 1),
                equity=Decimal("123456.789012345"),
                cash=Decimal("0.001"),
                positions_value=Decimal("123456.788012345"),
                drawdown=Decimal("0.000001"),
                cumulative_costs=Decimal("0.123456789"),
                contribution_today=Decimal("100000.00"),
                cumulative_traded_value=Decimal("99999.876543211"),
            ),
        ],
        metrics=SimulationMetrics(
            total_return=Decimal("0.23456789012345"),
            cagr=Decimal("0.11111111111111"),
            max_drawdown=Decimal("0.000001"),
            total_costs=Decimal("0.123456789"),
            total_contributions=Decimal("100000.00"),
            final_equity=Decimal("123456.789012345"),
            annualized_volatility=Decimal("0.98765432109876"),
            turnover=Decimal("0.80987654321"),
        ),
        curve_hash="precise_curve",
        policy_hash="precise_policy",
    )

    saved = await save_backtest_run(
        policy_id=policy.id,
        backtest_yaml=BACKTEST_YAML,
        config_hash="cfgprecise",
        simulation_result=precise_result,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        session=session,
    )
    await session.commit()

    fetched = await get_backtest_run(saved.run_id, session)

    assert fetched.metrics.total_return == Decimal("0.23456789012345")
    assert fetched.metrics.final_equity == Decimal("123456.789012345")
    assert fetched.curve[0].equity == Decimal("123456.789012345")
    assert fetched.curve[0].cumulative_costs == Decimal("0.123456789")
