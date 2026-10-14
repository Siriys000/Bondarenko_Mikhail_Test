from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from price_service.domain import CollectionFailed, Price, PriceNotFound, Ticker, UpstreamError
from price_service.services import PriceCollector, PriceQueryService
from tests.fakes import FakeClient, FrozenClock, MemoryRepository


async def test_collect_both_currencies_and_skip_completed_slot() -> None:
    repository = MemoryRepository()
    client = FakeClient()
    collector = PriceCollector(repository, client, FrozenClock(125))
    await collector.collect(120)
    await collector.collect(120)
    assert len(repository.prices) == 2
    assert set(client.calls) == set(Ticker)
    assert len(client.calls) == 2
    assert all(p.timestamp == 125 and p.collection_slot == 120 for p in repository.prices)


async def test_partial_success_survives_retry_across_minute_boundary() -> None:
    repository = MemoryRepository()
    client = FakeClient()
    client.errors[Ticker.ETH_USD] = UpstreamError("timeout", retryable=True)
    clock = FrozenClock(125)
    collector = PriceCollector(repository, client, clock)
    with pytest.raises(CollectionFailed):
        await collector.collect(120)
    assert [p.ticker for p in repository.prices] == [Ticker.BTC_USD]
    client.errors.clear()
    clock.now = 185
    await collector.collect(120)
    assert len(repository.prices) == 2
    assert client.calls.count(Ticker.BTC_USD) == 1
    assert repository.prices[-1].timestamp == 185
    assert repository.prices[-1].collection_slot == 120


async def test_permanent_upstream_error_does_not_retry_other_currency() -> None:
    repository = MemoryRepository()
    client = FakeClient()
    client.errors[Ticker.BTC_USD] = UpstreamError("bad request", retryable=False)
    await PriceCollector(repository, client, FrozenClock()).collect(120)
    assert [p.ticker for p in repository.prices] == [Ticker.ETH_USD]


async def test_latest_and_missing_price() -> None:
    older = Price(Ticker.BTC_USD, Decimal("2"), 61, 60)
    newer = Price(Ticker.BTC_USD, Decimal("3"), 121, 120)
    service = PriceQueryService(MemoryRepository([newer, older]))
    assert await service.latest(Ticker.BTC_USD) == newer
    with pytest.raises(PriceNotFound):
        await service.latest(Ticker.ETH_USD)
    assert await service.all_prices(Ticker.BTC_USD, limit=1, offset=1) == [newer]


async def test_history_includes_whole_final_day_and_excludes_next_day() -> None:
    start = int(datetime(2026, 10, 14, tzinfo=UTC).timestamp())
    prices = [
        Price(Ticker.BTC_USD, Decimal("1"), t, t - t % 60)
        for t in (start - 1, start, start + 86399, start + 86400)
    ]
    service = PriceQueryService(MemoryRepository(prices))
    result = await service.history(Ticker.BTC_USD, date(2026, 10, 14), date(2026, 10, 14))
    assert [p.timestamp for p in result] == [start, start + 86399]
    with pytest.raises(ValueError):
        await service.history(Ticker.BTC_USD, date(2026, 10, 15), date(2026, 10, 14))


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity"])
def test_domain_rejects_invalid_price(value: str) -> None:
    with pytest.raises(ValueError):
        Price(Ticker.BTC_USD, Decimal(value), 120, 120)


@pytest.mark.parametrize("timestamp,slot", [(-1, 120), (120, -60), (120, 121)])
def test_domain_rejects_invalid_time(timestamp: int, slot: int) -> None:
    with pytest.raises(ValueError):
        Price(Ticker.BTC_USD, Decimal("1"), timestamp, slot)
