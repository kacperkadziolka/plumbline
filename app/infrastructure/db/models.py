from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
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


class PriceDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (UniqueConstraint("date", "asset_id", name="uq_prices_daily_date_asset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date]
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    close: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))

    asset: Mapped["Asset"] = relationship()


class FxDaily(Base):
    __tablename__ = "fx_daily"
    __table_args__ = (UniqueConstraint("date", "pair", name="uq_fx_daily_date_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date]
    pair: Mapped[str] = mapped_column(String(7))
    rate: Mapped[Decimal]


class Policy(Base):
    __tablename__ = "policy"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    yaml_text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Proposal(Base):
    __tablename__ = "proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    policy_id: Mapped[int] = mapped_column(ForeignKey("policy.id"))
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    result_json: Mapped[str] = mapped_column(Text)

    policy: Mapped["Policy"] = relationship()


class BacktestRun(Base):
    __tablename__ = "backtest_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policy.id"))
    backtest_yaml: Mapped[str] = mapped_column(Text)
    config_hash: Mapped[str] = mapped_column(String(64))
    policy_hash: Mapped[str] = mapped_column(String(64))
    curve_hash: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date]
    end_date: Mapped[date]
    metrics_json: Mapped[str] = mapped_column(Text)
    curve_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    policy: Mapped["Policy"] = relationship()
