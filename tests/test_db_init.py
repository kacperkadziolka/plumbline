import tempfile
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, Meta


async def test_init_db_creates_holdings_tables() -> None:
    """Verify that init_db creates Asset, HoldingsSnapshot, and Position tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        engine = create_async_engine(db_url, echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.begin() as conn:
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

        expected_tables = {"asset", "holdings_snapshot", "position"}
        assert expected_tables.issubset(set(table_names)), f"Missing tables: {expected_tables - set(table_names)}"

        await engine.dispose()


async def test_db_init_creates_tables_and_allows_crud() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        engine = create_async_engine(db_url, echo=False)
        async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Insert a row
        async with async_session_factory() as session:
            meta_entry = Meta(key="test_key", value="test_value")
            session.add(meta_entry)
            await session.commit()

        # Read it back
        async with async_session_factory() as session:
            result = await session.execute(select(Meta).where(Meta.key == "test_key"))
            row = result.scalar_one()
            assert row.key == "test_key"
            assert row.value == "test_value"

        await engine.dispose()
