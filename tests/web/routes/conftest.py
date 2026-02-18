from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.db.db import engine
from app.main import app


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, Any]:
    """Per-module TestClient with a clean database.

    Overrides the root conftest client fixture to ensure each test module
    starts with empty tables, preventing cross-module data leaks.
    """
    with TestClient(app) as c:
        # Clean data tables after lifespan init_db() has created them
        import asyncio

        async def _clean() -> None:
            async with engine.begin() as conn:
                for table in (
                    "backtest_run",
                    "proposal",
                    "position",
                    "holdings_snapshot",
                    "prices_daily",
                    "fx_daily",
                    "policy",
                ):
                    await conn.execute(text(f"DELETE FROM {table}"))

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_clean())
        yield c
