import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, Meta


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
