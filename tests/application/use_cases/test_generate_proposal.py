from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.generate_proposal import (
    GenerateProposalResult,
    deserialize_allocation_result,
    generate_proposal,
    serialize_allocation_result,
)
from app.core.errors import DataMissingError, ValidationError
from app.domain.allocator import AllocationResult, TradeProposal
from app.infrastructure.db.repositories import (
    HoldingsRepository,
    PolicyRepository,
    PositionInput,
    PriceInput,
    PricesRepository,
)

VALID_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"


async def _seed_holdings_and_prices(session: AsyncSession, as_of: date) -> None:
    holdings_repo = HoldingsRepository(session)
    await holdings_repo.create_snapshot(
        as_of_date=datetime(as_of.year, as_of.month, as_of.day),
        positions=[
            PositionInput(ticker="IWDA.AS", qty=Decimal("10"), currency="EUR"),
            PositionInput(ticker="EIMI.AS", qty=Decimal("5"), currency="EUR"),
        ],
    )

    prices_repo = PricesRepository(session)
    assets = await prices_repo.get_assets_by_tickers({"IWDA.AS", "EIMI.AS"})
    await prices_repo.upsert_prices(
        [
            PriceInput(ticker="IWDA.AS", date=as_of, close=Decimal("80.00"), currency="EUR"),
            PriceInput(ticker="EIMI.AS", date=as_of, close=Decimal("30.00"), currency="EUR"),
        ],
        assets,
    )
    await session.flush()


async def test_generate_proposal_success(session: AsyncSession) -> None:
    today = date.today()
    await _seed_holdings_and_prices(session, today)

    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test-policy", VALID_YAML, "hash1")
    await session.flush()

    result = await generate_proposal(policy.id, Decimal("1000.00"), "EUR", False, session)

    assert isinstance(result, GenerateProposalResult)
    assert result.policy_id == policy.id
    assert result.policy_name == "test-policy"
    assert result.amount == Decimal("1000.00")
    assert result.currency == "EUR"
    assert result.include_satellite is False
    assert result.has_satellite_bucket is False
    assert result.allocation_result.total_allocated + result.allocation_result.unallocated == Decimal("1000.00")
    assert len(result.allocation_result.trades) > 0


async def test_generate_proposal_policy_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError) as exc_info:
        await generate_proposal(99999, Decimal("1000.00"), "EUR", False, session)

    assert "Policy not found" in exc_info.value.message


async def test_generate_proposal_no_holdings(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test-policy", VALID_YAML, "hash2")
    await session.flush()

    with pytest.raises(DataMissingError) as exc_info:
        await generate_proposal(policy.id, Decimal("1000.00"), "EUR", False, session)

    assert "holdings" in exc_info.value.message.lower()


async def test_generate_proposal_currency_mismatch(session: AsyncSession) -> None:
    today = date.today()
    await _seed_holdings_and_prices(session, today)

    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test-policy", VALID_YAML, "hash3")
    await session.flush()

    with pytest.raises(ValidationError):
        await generate_proposal(policy.id, Decimal("1000.00"), "USD", False, session)


def test_serialize_deserialize_roundtrip() -> None:
    original = AllocationResult(
        trades=[
            TradeProposal(
                ticker="IWDA.AS",
                buy_amount=Decimal("600.00"),
                current_weight=Decimal("0.20"),
                target_weight=Decimal("0.60"),
                gap=Decimal("0.40"),
            ),
            TradeProposal(
                ticker="EIMI.AS",
                buy_amount=Decimal("400.00"),
                current_weight=Decimal("0.10"),
                target_weight=Decimal("0.40"),
                gap=Decimal("0.30"),
            ),
        ],
        total_allocated=Decimal("1000.00"),
        unallocated=Decimal("0.00"),
        policy_hash="abc123def456",
    )

    json_str = serialize_allocation_result(original)
    restored = deserialize_allocation_result(json_str)

    assert restored.trades == original.trades
    assert restored.total_allocated == original.total_allocated
    assert restored.unallocated == original.unallocated
    assert restored.policy_hash == original.policy_hash


def test_serialize_deserialize_empty_trades() -> None:
    original = AllocationResult(
        trades=[],
        total_allocated=Decimal("0"),
        unallocated=Decimal("1000.00"),
        policy_hash="empty_hash",
    )

    json_str = serialize_allocation_result(original)
    restored = deserialize_allocation_result(json_str)

    assert restored.trades == []
    assert restored.total_allocated == Decimal("0")
    assert restored.unallocated == Decimal("1000.00")
