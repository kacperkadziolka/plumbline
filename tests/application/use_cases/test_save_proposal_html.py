from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.save_proposal import save_proposal
from app.application.use_cases.save_proposal_html import save_proposal_html
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
        ],
        total_allocated=Decimal("400.00"),
        unallocated=Decimal("100.00"),
        policy_hash="abc123",
    )


async def test_save_html_creates_file(session: AsyncSession, tmp_path: Path) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash1")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("500.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    target_dir = tmp_path / "reports" / "proposals"
    with patch("app.application.use_cases.save_proposal_html.REPORTS_DIR", target_dir):
        result_path = await save_proposal_html(saved.proposal_id, session)

    assert result_path.exists()
    assert result_path.name == f"{saved.proposal_id}.html"

    content = result_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "EIMI.AS" in content


async def test_save_html_creates_directory(session: AsyncSession, tmp_path: Path) -> None:
    policy_repo = PolicyRepository(session)
    policy = await policy_repo.save("test", VALID_YAML, "hash2")
    await session.flush()

    saved = await save_proposal(policy.id, Decimal("500.00"), "EUR", _make_allocation_result(), session)
    await session.commit()

    target_dir = tmp_path / "new" / "nested" / "dir"
    assert not target_dir.exists()

    with patch("app.application.use_cases.save_proposal_html.REPORTS_DIR", target_dir):
        result_path = await save_proposal_html(saved.proposal_id, session)

    assert target_dir.exists()
    assert result_path.exists()
