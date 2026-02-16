from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.export_proposal_html import export_proposal_html
from app.application.use_cases.save_proposal import save_proposal
from app.core.errors import DataMissingError
from app.domain.allocator import AllocationResult, TradeProposal
from app.infrastructure.db.repositories import PolicyRepository

VALID_YAML = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      IWDA.AS: 0.60\n      EIMI.AS: 0.40\n"


def _make_allocation_result() -> AllocationResult:
    return AllocationResult(
        trades=[
            TradeProposal(
                ticker="EIMI.AS",
                buy_amount=Decimal("400.00"),
                current_weight=Decimal("0.10"),
                target_weight=Decimal("0.40"),
                gap=Decimal("0.30"),
            ),
            TradeProposal(
                ticker="IWDA.AS",
                buy_amount=Decimal("600.00"),
                current_weight=Decimal("0.20"),
                target_weight=Decimal("0.60"),
                gap=Decimal("0.40"),
            ),
        ],
        total_allocated=Decimal("1000.00"),
        unallocated=Decimal("0.00"),
        policy_hash="abc123def456",
    )


async def _save_test_proposal(session: AsyncSession) -> int:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test-policy", VALID_YAML, "hash1")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("1000.00"), "EUR", _make_allocation_result(), session)
    await session.commit()
    return saved.proposal_id


async def test_html_is_valid_document(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "<head>" in html
    assert "<style>" in html
    assert "<body>" in html
    assert "</html>" in html


async def test_html_has_no_external_dependencies(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert "cdn.tailwindcss.com" not in html
    assert "unpkg.com" not in html
    assert '<link rel="stylesheet"' not in html
    assert "<script src=" not in html


async def test_html_contains_proposal_metadata(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert f"#{proposal_id}" in html
    assert "abc123def456" in html  # policy_hash (or truncated prefix)


async def test_html_contains_summary_values(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert "1000.00" in html  # amount
    assert "EUR" in html  # currency
    assert "0.00" in html  # unallocated


async def test_html_contains_trade_table(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert "<table>" in html
    assert "EIMI.AS" in html
    assert "IWDA.AS" in html
    assert "400.00" in html  # EIMI buy amount
    assert "600.00" in html  # IWDA buy amount


async def test_html_formats_percentages(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert "10.0%" in html  # EIMI current_weight
    assert "40.0%" in html  # EIMI target_weight
    assert "30.0%" in html  # EIMI gap


async def test_html_contains_explanations(session: AsyncSession) -> None:
    proposal_id = await _save_test_proposal(session)
    html = await export_proposal_html(proposal_id, session)

    assert "Buy Amount" in html
    assert "Current %" in html
    assert "Target %" in html
    assert "Gap %" in html


async def test_html_raises_when_not_found(session: AsyncSession) -> None:
    with pytest.raises(DataMissingError):
        await export_proposal_html(99999, session)


async def test_html_with_empty_trades(session: AsyncSession) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash2")
    await session.flush()

    empty_result = AllocationResult(
        trades=[],
        total_allocated=Decimal("0"),
        unallocated=Decimal("500.00"),
        policy_hash="empty_hash",
    )
    saved = await save_proposal(policy.id, Decimal("500.00"), "EUR", empty_result, session)
    await session.commit()

    html = await export_proposal_html(saved.proposal_id, session)

    assert "<table>" not in html
    assert "No trades needed" in html
