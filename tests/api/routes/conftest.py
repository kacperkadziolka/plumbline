import asyncio
import itertools
import json
from collections.abc import Generator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.db.db import async_session_factory, engine
from app.infrastructure.db.models import Policy, Proposal
from app.main import app

_counter = itertools.count()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, Any]:
    """Per-module TestClient with a clean database."""
    with TestClient(app) as c:

        async def _clean() -> None:
            async with engine.begin() as conn:
                for table in ("proposal", "position", "holdings_snapshot", "prices_daily", "fx_daily", "policy"):
                    await conn.execute(text(f"DELETE FROM {table}"))

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_clean())
        yield c


def _seed_proposal(amount: Decimal = Decimal("1000.00"), currency: str = "EUR") -> int:
    """Seed a policy and proposal into the live DB. Returns proposal_id."""
    result_json = json.dumps(
        {
            "trades": [
                {
                    "ticker": "IWDA.AS",
                    "buy_amount": str(Decimal("600.00")),
                    "current_weight": str(Decimal("0.20")),
                    "target_weight": str(Decimal("0.60")),
                    "gap": str(Decimal("0.40")),
                },
                {
                    "ticker": "EIMI.AS",
                    "buy_amount": str(Decimal("400.00")),
                    "current_weight": str(Decimal("0.10")),
                    "target_weight": str(Decimal("0.40")),
                    "gap": str(Decimal("0.30")),
                },
            ],
            "total_allocated": str(amount),
            "unallocated": "0.00",
            "policy_hash": "seeded_hash_for_test",
        }
    )

    proposal_id: int = 0

    async def _insert() -> None:
        nonlocal proposal_id
        async with async_session_factory() as session:
            n = next(_counter)
            policy = Policy(name="test-policy", yaml_text="base_currency: EUR\n", hash=f"seeded_policy_hash_{n}")
            session.add(policy)
            await session.flush()

            proposal = Proposal(
                policy_id=policy.id,
                amount=amount,
                currency=currency,
                result_json=result_json,
            )
            session.add(proposal)
            await session.flush()
            proposal_id = proposal.id
            await session.commit()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_insert())
    return proposal_id
