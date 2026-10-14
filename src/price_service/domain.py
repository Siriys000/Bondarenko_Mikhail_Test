"""Business values and ports; independent of HTTP, Celery and SQLAlchemy."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class Ticker(StrEnum):
    BTC_USD = "btc_usd"
    ETH_USD = "eth_usd"


@dataclass(frozen=True, slots=True)
class Price:
    ticker: Ticker
    price: Decimal
    timestamp: int
    collection_slot: int

    def __post_init__(self) -> None:
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("Price must be finite and positive")
        if self.timestamp < 0 or self.collection_slot < 0 or self.collection_slot % 60:
            raise ValueError("Timestamps must be nonnegative and slot aligned to a minute")


class PriceRepository(Protocol):
    async def list_prices(
        self,
        ticker: Ticker,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Price]: ...

    async def latest(self, ticker: Ticker) -> Price | None: ...

    async def exists(self, ticker: Ticker, collection_slot: int) -> bool: ...

    async def save(self, price: Price) -> bool:
        """Atomically insert; return False if the minute slot is already present."""
        ...


class IndexPriceClient(Protocol):
    async def get_index_price(self, ticker: Ticker) -> Decimal: ...


class Clock(Protocol):
    def timestamp(self) -> int: ...


class UpstreamError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class CollectionFailed(Exception):
    """At least one transient failure; successful currencies are already committed."""


class PriceNotFound(Exception):
    pass
