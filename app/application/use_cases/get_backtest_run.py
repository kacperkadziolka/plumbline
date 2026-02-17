import json
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.infrastructure.db.repositories import BacktestRunRepository


class CurveRow(BaseModel):
    date: date
    equity: Decimal
    cash: Decimal
    positions_value: Decimal
    drawdown: Decimal
    cumulative_costs: Decimal
    contribution_today: Decimal
    cumulative_traded_value: Decimal


class MetricsSummary(BaseModel):
    total_return: Decimal
    cagr: Decimal | None
    max_drawdown: Decimal
    total_costs: Decimal
    total_contributions: Decimal
    final_equity: Decimal
    annualized_volatility: Decimal | None
    turnover: Decimal


class GetBacktestRunResult(BaseModel):
    run_id: int
    policy_id: int
    backtest_yaml: str
    config_hash: str
    policy_hash: str
    curve_hash: str
    start_date: date
    end_date: date
    created_at: datetime
    metrics: MetricsSummary
    curve: list[CurveRow]


def _deserialize_metrics(metrics_json: str) -> MetricsSummary:
    data = json.loads(metrics_json)
    return MetricsSummary(
        total_return=Decimal(data["total_return"]),
        cagr=Decimal(data["cagr"]) if data["cagr"] is not None else None,
        max_drawdown=Decimal(data["max_drawdown"]),
        total_costs=Decimal(data["total_costs"]),
        total_contributions=Decimal(data["total_contributions"]),
        final_equity=Decimal(data["final_equity"]),
        annualized_volatility=Decimal(data["annualized_volatility"])
        if data["annualized_volatility"] is not None
        else None,
        turnover=Decimal(data["turnover"]),
    )


def _deserialize_curve(curve_json: str) -> list[CurveRow]:
    data = json.loads(curve_json)
    return [
        CurveRow(
            date=date.fromisoformat(row["date"]),
            equity=Decimal(row["equity"]),
            cash=Decimal(row["cash"]),
            positions_value=Decimal(row["positions_value"]),
            drawdown=Decimal(row["drawdown"]),
            cumulative_costs=Decimal(row["cumulative_costs"]),
            contribution_today=Decimal(row["contribution_today"]),
            cumulative_traded_value=Decimal(row["cumulative_traded_value"]),
        )
        for row in data
    ]


async def get_backtest_run(
    run_id: int,
    session: AsyncSession,
) -> GetBacktestRunResult:
    """Retrieve a backtest run by ID, deserializing its metrics and curve JSON.

    Note: Does not commit. Caller owns the transaction boundary.

    Raises:
        DataMissingError: If no backtest run with this ID exists.
    """
    repo = BacktestRunRepository(session)
    run = await repo.get_by_id(run_id)
    if run is None:
        raise DataMissingError(
            message="Backtest run not found",
            details=f"No backtest run with id={run_id}",
        )

    return GetBacktestRunResult(
        run_id=run.id,
        policy_id=run.policy_id,
        backtest_yaml=run.backtest_yaml,
        config_hash=run.config_hash,
        policy_hash=run.policy_hash,
        curve_hash=run.curve_hash,
        start_date=run.start_date,
        end_date=run.end_date,
        created_at=run.created_at,
        metrics=_deserialize_metrics(run.metrics_json),
        curve=_deserialize_curve(run.curve_json),
    )
