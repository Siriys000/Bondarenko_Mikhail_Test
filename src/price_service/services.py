import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from price_service.domain import (
    Clock,
    CollectionFailed,
    IndexPriceClient,
    Price,
    PriceNotFound,
    PriceRepository,
    Ticker,
    UpstreamError,
)


class SystemClock:
    def timestamp(self) -> int:
        return int(datetime.now(UTC).timestamp())


class PriceQueryService:
    def __init__(self, repository: PriceRepository) -> None:
        self._repository = repository

    async def all_prices(
        self, ticker: Ticker, *, limit: int | None = None, offset: int = 0
    ) -> list[Price]:
        return await self._repository.list_prices(ticker, limit=limit, offset=offset)

    async def latest(self, ticker: Ticker) -> Price:
        price = await self._repository.latest(ticker)
        if price is None:
            raise PriceNotFound(f"No prices stored for {ticker}")
        return price

    async def history(
        self,
        ticker: Ticker,
        date_from: date,
        date_to: date,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Price]:
        if date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        start = int(datetime.combine(date_from, datetime.min.time(), UTC).timestamp())
        # An exclusive upper bound includes every second of the last calendar day.
        end = int(
            (datetime.combine(date_to, datetime.min.time(), UTC) + timedelta(days=1)).timestamp()
        )
        return await self._repository.list_prices(
            ticker, start=start, end=end, limit=limit, offset=offset
        )


class PriceCollector:
    def __init__(self, repository: PriceRepository, client: IndexPriceClient, clock: Clock) -> None:
        self._repository = repository
        self._client = client
        self._clock = clock
        self._logger = logging.getLogger(__name__)

    async def collect(self, collection_slot: int) -> None:
        outcomes = await asyncio.gather(
            *(self._collect_one(ticker, collection_slot) for ticker in Ticker),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome
        if not all(outcomes):
            raise CollectionFailed("Transient collection failure; retry the same minute slot")

    async def _collect_one(self, ticker: Ticker, collection_slot: int) -> bool:
        if await self._repository.exists(ticker, collection_slot):
            return True
        try:
            value = await self._client.get_index_price(ticker)
        except UpstreamError as exc:
            self._logger.warning("Index fetch failed ticker=%s error=%s", ticker, exc)
            return not exc.retryable
        price = Price(ticker, value, self._clock.timestamp(), collection_slot)
        inserted = await self._repository.save(price)
        self._logger.info(
            "Collection ticker=%s slot=%s inserted=%s", ticker, collection_slot, inserted
        )
        return True
