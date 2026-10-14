from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Index, Numeric, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from price_service.domain import Price, Ticker


class Base(DeclarativeBase):
    pass


class PriceRecord(Base):
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("ticker", "collection_slot", name="uq_prices_ticker_slot"),
        CheckConstraint("price > 0", name="ck_prices_positive_price"),
        CheckConstraint("timestamp >= 0", name="ck_prices_timestamp"),
        CheckConstraint(
            "collection_slot >= 0 AND collection_slot % 60 = 0", name="ck_prices_minute_slot"
        ),
        CheckConstraint("ticker IN ('btc_usd', 'eth_usd')", name="ck_prices_ticker"),
        Index("ix_prices_ticker_timestamp_id", "ticker", "timestamp", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(7), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    collection_slot: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def to_domain(self) -> Price:
        return Price(Ticker(self.ticker), self.price, self.timestamp, self.collection_slot)


class SqlAlchemyPriceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_prices(
        self,
        ticker: Ticker,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Price]:
        statement = select(PriceRecord).where(PriceRecord.ticker == ticker.value)
        if start is not None:
            statement = statement.where(PriceRecord.timestamp >= start)
        if end is not None:
            statement = statement.where(PriceRecord.timestamp < end)
        statement = statement.order_by(PriceRecord.timestamp, PriceRecord.id).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        async with self._sessions() as session:
            records = await session.scalars(statement)
            return [record.to_domain() for record in records]

    async def latest(self, ticker: Ticker) -> Price | None:
        statement = (
            select(PriceRecord)
            .where(PriceRecord.ticker == ticker.value)
            .order_by(PriceRecord.timestamp.desc(), PriceRecord.id.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
            return record.to_domain() if record is not None else None

    async def exists(self, ticker: Ticker, collection_slot: int) -> bool:
        statement = select(PriceRecord.id).where(
            PriceRecord.ticker == ticker.value, PriceRecord.collection_slot == collection_slot
        )
        async with self._sessions() as session:
            return await session.scalar(statement) is not None

    async def save(self, price: Price) -> bool:
        statement = (
            insert(PriceRecord)
            .values(
                ticker=price.ticker.value,
                price=price.price,
                timestamp=price.timestamp,
                collection_slot=price.collection_slot,
            )
            .on_conflict_do_nothing(constraint="uq_prices_ticker_slot")
            .returning(PriceRecord.id)
        )
        async with self._sessions.begin() as session:
            inserted_id = await session.scalar(statement)
        return inserted_id is not None
