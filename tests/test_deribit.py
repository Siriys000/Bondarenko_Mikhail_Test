import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from price_service.domain import Ticker, UpstreamError
from price_service.infrastructure.deribit import DeribitClient


@asynccontextmanager
async def deribit_response(
    body: str, status: int = 200, *, ticker: Ticker = Ticker.BTC_USD, delay: float = 0
) -> AsyncIterator[DeribitClient]:
    async def handler(request: web.Request) -> web.Response:
        assert request.query["index_name"] == ticker.value
        if delay:
            await asyncio.sleep(delay)
        return web.Response(text=body, status=status, content_type="application/json")

    app = web.Application()
    app.router.add_get("/api/v2/public/get_index_price", handler)
    async with TestServer(app) as server:
        timeout = aiohttp.ClientTimeout(total=0.01 if delay else 2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            yield DeribitClient(session, str(server.make_url("/api/v2/")))


@pytest.mark.parametrize("ticker", list(Ticker))
async def test_request_contract_and_decimal_precision(ticker: Ticker) -> None:
    body = (
        '{"jsonrpc":"2.0","result":{"index_price":60000.123456789012,'
        '"estimated_delivery_price":1},"usOut":123}'
    )
    async with deribit_response(body, ticker=ticker) as client:
        assert await client.get_index_price(ticker) == Decimal("60000.123456789012")


@pytest.mark.parametrize("status,retryable", [(400, False), (408, True), (429, True), (503, True)])
async def test_http_errors(status: int, retryable: bool) -> None:
    async with deribit_response("{}", status) as client:
        with pytest.raises(UpstreamError) as error:
            await client.get_index_price(Ticker.BTC_USD)
    assert error.value.retryable is retryable


@pytest.mark.parametrize(
    "code,retryable",
    [
        (10028, True),
        (10040, True),
        (10066, True),
        (11051, True),
        (11094, True),
        (11050, False),
        (10004, False),
    ],
)
async def test_json_rpc_errors_even_with_http_200(code: int, retryable: bool) -> None:
    await assert_invalid_response(
        json.dumps({"jsonrpc": "2.0", "error": {"code": code, "message": "error"}}), retryable
    )


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '{"jsonrpc":"2.0","result":{}}',
        '{"jsonrpc":"2.0","result":{"index_price":-1}}',
        '{"jsonrpc":"2.0","result":{"index_price":"NaN"}}',
        '{"jsonrpc":"1.0","result":{"index_price":1}}',
        '{"jsonrpc":"2.0","result":{"index_price":0.1234567890123}}',
    ],
)
async def test_malformed_response(body: str) -> None:
    await assert_invalid_response(body, False)


async def assert_invalid_response(body: str, retryable: bool) -> None:
    async with deribit_response(body) as client:
        with pytest.raises(UpstreamError) as error:
            await client.get_index_price(Ticker.BTC_USD)
    assert error.value.retryable is retryable


async def test_timeout_is_retryable() -> None:
    async with deribit_response("{}", delay=0.03) as client:
        with pytest.raises(UpstreamError) as error:
            await client.get_index_price(Ticker.BTC_USD)
    assert error.value.retryable
