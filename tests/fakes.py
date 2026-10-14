from decimal import Decimal

from price_service.domain import Price, Ticker, UpstreamError


class MemoryRepository:
    def __init__(self, prices: list[Price] | None = None) -> None:
        self.prices = list(prices or [])

    async def list_prices(
        self,
        ticker: Ticker,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Price]:
        prices = sorted(
            (
                price
                for price in self.prices
                if price.ticker == ticker
                and (start is None or price.timestamp >= start)
                and (end is None or price.timestamp < end)
            ),
            key=lambda price: price.timestamp,
        )
        return prices[offset:] if limit is None else prices[offset : offset + limit]

    async def latest(self, ticker: Ticker) -> Price | None:
        prices = await self.list_prices(ticker)
        return prices[-1] if prices else None

    async def exists(self, ticker: Ticker, collection_slot: int) -> bool:
        return any(p.ticker == ticker and p.collection_slot == collection_slot for p in self.prices)

    async def save(self, price: Price) -> bool:
        if await self.exists(price.ticker, price.collection_slot):
            return False
        self.prices.append(price)
        return True


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[Ticker] = []
        self.errors: dict[Ticker, UpstreamError] = {}

    async def get_index_price(self, ticker: Ticker) -> Decimal:
        self.calls.append(ticker)
        if ticker in self.errors:
            raise self.errors[ticker]
        return Decimal("60000.123456789012") if ticker == Ticker.BTC_USD else Decimal("3000.5")


class FrozenClock:
    def __init__(self, now: int = 120) -> None:
        self.now = now

    def timestamp(self) -> int:
        return self.now
