import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from price_service.api.app import create_app
from price_service.domain import Price, Ticker
from price_service.infrastructure.database import PriceRecord, SqlAlchemyPriceRepository
from price_service.settings import Settings
from price_service.worker import collect_prices


@pytest.fixture
async def repository() -> AsyncIterator[SqlAlchemyPriceRepository]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(delete(PriceRecord))
        yield SqlAlchemyPriceRepository(sessions)
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(PriceRecord))
        await engine.dispose()


@pytest.mark.integration
async def test_repository_precision_filtering_and_latest(
    repository: SqlAlchemyPriceRepository,
) -> None:
    older = Price(Ticker.BTC_USD, Decimal("60000.123456789012"), 120, 120)
    newer = Price(Ticker.BTC_USD, Decimal("60001"), 180, 180)
    await repository.save(newer)
    await repository.save(older)
    await repository.save(Price(Ticker.ETH_USD, Decimal("3000"), 120, 120))
    assert await repository.list_prices(Ticker.BTC_USD) == [older, newer]
    assert await repository.latest(Ticker.BTC_USD) == newer
    assert await repository.list_prices(Ticker.BTC_USD, start=120, end=180) == [older]
    assert await repository.list_prices(Ticker.BTC_USD, limit=1, offset=1) == [newer]
    assert await repository.list_prices(Ticker.ETH_USD, start=180) == []
    assert await repository.exists(Ticker.BTC_USD, 120)
    assert not await repository.exists(Ticker.BTC_USD, 240)


@pytest.mark.integration
async def test_concurrent_insert_is_idempotent(repository: SqlAlchemyPriceRepository) -> None:
    price = Price(Ticker.BTC_USD, Decimal("60000"), 125, 120)
    results = await asyncio.gather(*(repository.save(price) for _ in range(5)))
    assert results.count(True) == 1
    assert len(await repository.list_prices(Ticker.BTC_USD)) == 1
    assert not await repository.save(Price(Ticker.BTC_USD, Decimal("60001"), 126, 120))
    assert await repository.latest(Ticker.BTC_USD) == price


@pytest.mark.integration
async def test_empty_repository(repository: SqlAlchemyPriceRepository) -> None:
    assert await repository.latest(Ticker.BTC_USD) is None
    assert await repository.list_prices(Ticker.ETH_USD) == []


@pytest.mark.integration
async def test_worker_collection_is_readable_through_api(
    repository: SqlAlchemyPriceRepository,
) -> None:
    requests: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        requests.append(request.query["index_name"])
        return web.Response(
            text='{"jsonrpc":"2.0","result":{"index_price":123.123456789012}}',
            content_type="application/json",
        )

    app = web.Application()
    app.router.add_get("/api/v2/public/get_index_price", handler)
    async with TestServer(app) as server:
        settings = Settings(
            database_url=os.environ["TEST_DATABASE_URL"],
            deribit_base_url=str(server.make_url("/api/v2")),
        )
        await collect_prices(settings, 120)
        await collect_prices(settings, 120)
    assert sorted(requests) == ["btc_usd", "eth_usd"]
    assert len(await repository.list_prices(Ticker.BTC_USD)) == 1
    with TestClient(create_app(settings)) as client:
        response = client.get("/prices/latest?ticker=btc_usd")
        assert response.status_code == 200
        assert response.json()["price"] == "123.123456789012"
        assert response.json()["timestamp"] > 120


@pytest.mark.integration
async def test_database_constraints() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine)
    try:
        for invalid in ({"ticker": "doge"}, {"price": -1}, {"collection_slot": 121}):
            values: dict[str, object] = {
                "ticker": "btc_usd",
                "price": 1,
                "timestamp": 120,
                "collection_slot": 120,
            }
            values.update(invalid)
            with pytest.raises(IntegrityError):
                async with sessions.begin() as session:
                    session.add(PriceRecord(**values))
    finally:
        await engine.dispose()
