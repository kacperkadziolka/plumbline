import json
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DataMissingError
from app.domain.allocator import AllocationResult, TradeProposal, allocate_contribution
from app.domain.policy import parse_policy_yaml
from app.infrastructure.db.repositories import PolicyRepository

from .valuate_portfolio import get_domain_valuation


class GenerateProposalResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    allocation_result: AllocationResult
    policy_id: int
    policy_name: str
    amount: Decimal
    currency: str
    include_satellite: bool
    has_satellite_bucket: bool


async def generate_proposal(
    policy_id: int,
    amount: Decimal,
    currency: str,
    include_satellite: bool,
    session: AsyncSession,
) -> GenerateProposalResult:
    """Generate a contribution allocation proposal.

    Orchestrates: fetch policy -> parse -> get valuation -> allocate.

    Note: Does not commit. Read-only operation.

    Raises:
        DataMissingError: If policy or holdings/prices/FX data is missing.
        ValidationError: If inputs are invalid (amount, currency, etc.).
    """
    repo = PolicyRepository(session)
    policy = await repo.get_by_id(policy_id)
    if policy is None:
        raise DataMissingError(
            message="Policy not found",
            details=f"No policy with id={policy_id}",
        )

    policy_config = parse_policy_yaml(policy.yaml_text)
    valuation = await get_domain_valuation(date.today(), session)
    allocation = allocate_contribution(valuation, policy_config, amount, currency, include_satellite)

    return GenerateProposalResult(
        allocation_result=allocation,
        policy_id=policy.id,
        policy_name=policy.name,
        amount=amount,
        currency=currency,
        include_satellite=include_satellite,
        has_satellite_bucket=policy_config.buckets.satellite is not None,
    )


def serialize_allocation_result(result: AllocationResult) -> str:
    return json.dumps(
        {
            "trades": [
                {
                    "ticker": t.ticker,
                    "buy_amount": str(t.buy_amount),
                    "current_weight": str(t.current_weight),
                    "target_weight": str(t.target_weight),
                    "gap": str(t.gap),
                }
                for t in result.trades
            ],
            "total_allocated": str(result.total_allocated),
            "unallocated": str(result.unallocated),
            "policy_hash": result.policy_hash,
        },
    )


def deserialize_allocation_result(json_str: str) -> AllocationResult:
    data = json.loads(json_str)
    trades = [
        TradeProposal(
            ticker=t["ticker"],
            buy_amount=Decimal(t["buy_amount"]),
            current_weight=Decimal(t["current_weight"]),
            target_weight=Decimal(t["target_weight"]),
            gap=Decimal(t["gap"]),
        )
        for t in data["trades"]
    ]
    return AllocationResult(
        trades=trades,
        total_allocated=Decimal(data["total_allocated"]),
        unallocated=Decimal(data["unallocated"]),
        policy_hash=data["policy_hash"],
    )
