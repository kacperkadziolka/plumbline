from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import BacktestRunRepository


class BacktestRunSummary(BaseModel):
    run_id: int
    policy_id: int
    config_hash: str
    policy_hash: str
    curve_hash: str
    start_date: date
    end_date: date
    created_at: datetime


class ListBacktestRunsResult(BaseModel):
    runs: list[BacktestRunSummary]
    count: int


async def list_backtest_runs(
    session: AsyncSession,
    policy_id: int | None = None,
    limit: int = 100,
) -> ListBacktestRunsResult:
    """List stored backtest runs ordered by created_at descending.

    Optionally filters by policy_id.

    Note: Does not commit. Caller owns the transaction boundary.
    """
    repo = BacktestRunRepository(session)
    runs = await repo.list_runs(policy_id=policy_id, limit=limit)

    summaries = [
        BacktestRunSummary(
            run_id=r.id,
            policy_id=r.policy_id,
            config_hash=r.config_hash,
            policy_hash=r.policy_hash,
            curve_hash=r.curve_hash,
            start_date=r.start_date,
            end_date=r.end_date,
            created_at=r.created_at,
        )
        for r in runs
    ]

    return ListBacktestRunsResult(runs=summaries, count=len(summaries))
