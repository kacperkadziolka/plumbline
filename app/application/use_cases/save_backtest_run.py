import json
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.domain.simulator import EquityCurveRow, SimulationMetrics, SimulationResult
from app.infrastructure.db.repositories import BacktestRunRepository, PolicyRepository


class SaveBacktestRunResult(BaseModel):
    run_id: int
    policy_id: int
    config_hash: str
    policy_hash: str
    curve_hash: str
    start_date: date
    end_date: date
    created_at: datetime


def _serialize_metrics(metrics: SimulationMetrics) -> str:
    return json.dumps(
        {
            "total_return": str(metrics.total_return),
            "cagr": str(metrics.cagr) if metrics.cagr is not None else None,
            "max_drawdown": str(metrics.max_drawdown),
            "total_costs": str(metrics.total_costs),
            "total_contributions": str(metrics.total_contributions),
            "final_equity": str(metrics.final_equity),
            "annualized_volatility": (
                str(metrics.annualized_volatility) if metrics.annualized_volatility is not None else None
            ),
            "turnover": str(metrics.turnover),
        },
    )


def _serialize_curve(curve: list[EquityCurveRow]) -> str:
    return json.dumps(
        [
            {
                "date": row.date.isoformat(),
                "equity": str(row.equity),
                "cash": str(row.cash),
                "positions_value": str(row.positions_value),
                "drawdown": str(row.drawdown),
                "cumulative_costs": str(row.cumulative_costs),
                "contribution_today": str(row.contribution_today),
                "cumulative_traded_value": str(row.cumulative_traded_value),
            }
            for row in curve
        ],
    )


async def save_backtest_run(
    policy_id: int,
    backtest_yaml: str,
    config_hash: str,
    simulation_result: SimulationResult,
    start_date: date,
    end_date: date,
    session: AsyncSession,
) -> SaveBacktestRunResult:
    """Persist a backtest run (simulation result) to the database.

    Validates that the referenced policy exists, serializes the SimulationResult
    (metrics + equity curve) to JSON, and saves via BacktestRunRepository.

    Note: Does not commit. Caller owns the transaction boundary.

    Raises:
        DataMissingError: If no policy with the given ID exists.
    """
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.get_by_id(policy_id)
    if policy is None:
        raise DataMissingError(
            message="Policy not found",
            details=f"No policy with id={policy_id}",
        )

    metrics_json = _serialize_metrics(simulation_result.metrics)
    curve_json = _serialize_curve(simulation_result.curve)

    repo = BacktestRunRepository(session)
    run = await repo.save(
        policy_id=policy_id,
        backtest_yaml=backtest_yaml,
        config_hash=config_hash,
        policy_hash=simulation_result.policy_hash,
        curve_hash=simulation_result.curve_hash,
        start_date=start_date,
        end_date=end_date,
        metrics_json=metrics_json,
        curve_json=curve_json,
    )

    return SaveBacktestRunResult(
        run_id=run.id,
        policy_id=run.policy_id,
        config_hash=run.config_hash,
        policy_hash=run.policy_hash,
        curve_hash=run.curve_hash,
        start_date=run.start_date,
        end_date=run.end_date,
        created_at=run.created_at,
    )
