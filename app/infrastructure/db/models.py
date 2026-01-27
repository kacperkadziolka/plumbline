from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024))


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    asset_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(255))

    positions: Mapped[list["Position"]] = relationship(back_populates="asset")


class HoldingsSnapshot(Base):
    __tablename__ = "holdings_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of_date: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    positions: Mapped[list["Position"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class Position(Base):
    __tablename__ = "position"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("holdings_snapshot.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    qty: Mapped[Decimal]

    snapshot: Mapped["HoldingsSnapshot"] = relationship(back_populates="positions")
    asset: Mapped["Asset"] = relationship(back_populates="positions")
