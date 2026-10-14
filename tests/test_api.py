from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from price_service.api.app import create_app
from price_service.api.routes import get_query_service
from price_service.domain import Price, Ticker
from price_service.services import PriceQueryService
from tests.fakes import MemoryRepository


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    app = create_app()
    repository = MemoryRepository(
        [
            Price(Ticker.BTC_USD, Decimal("60000.123456789012"), 1791936000, 1791936000),
            Price(Ticker.BTC_USD, Decimal("60001"), 1791936060, 1791936060),
            Price(Ticker.ETH_USD, Decimal("3000"), 1791936000, 1791936000),
        ]
    )
    service = PriceQueryService(repository)
    app.dependency_overrides[get_query_service] = lambda: service
    with TestClient(app) as client:
        yield client


def test_all_prices_ticker_normalization_and_pagination(api_client: TestClient) -> None:
    response = api_client.get("/prices", params={"ticker": "BTC_USD"})
    assert response.status_code == 200
    assert response.json() == [
        {"ticker": "btc_usd", "price": "60000.123456789012", "timestamp": 1791936000},
        {"ticker": "btc_usd", "price": "60001", "timestamp": 1791936060},
    ]
    page = api_client.get("/prices", params={"ticker": "btc_usd", "limit": 1, "offset": 1})
    assert page.json() == [response.json()[1]]


def test_latest_and_empty_data() -> None:
    app = create_app()
    app.dependency_overrides[get_query_service] = lambda: PriceQueryService(MemoryRepository())
    with TestClient(app) as client:
        assert client.get("/prices/latest?ticker=btc_usd").status_code == 404
        assert client.get("/prices?ticker=btc_usd").json() == []
        assert (
            client.get(
                "/prices/history?ticker=btc_usd&date_from=2026-10-14&date_to=2026-10-14"
            ).json()
            == []
        )


def test_latest_returns_single_object(api_client: TestClient) -> None:
    response = api_client.get("/prices/latest?ticker=btc_usd")
    assert response.status_code == 200
    assert response.json()["price"] == "60001"


def test_history_calendar_dates(api_client: TestClient) -> None:
    response = api_client.get(
        "/prices/history?ticker=btc_usd&date_from=2026-10-14&date_to=2026-10-14"
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.parametrize("path", ["/prices", "/prices/latest", "/prices/history"])
def test_ticker_is_required_and_validated(api_client: TestClient, path: str) -> None:
    assert api_client.get(path).status_code == 422
    assert api_client.get(path, params={"ticker": "doge_usd"}).status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "date_from=2026-10-15&date_to=2026-10-14",
        "date_from=invalid&date_to=2026-10-14",
        "date_from=1791936000&date_to=2026-10-14",
        "date_from=20261014&date_to=2026-10-14",
        "date_from=1969-12-31&date_to=2026-10-14",
        "date_from=2026-10-14&date_to=9999-12-31",
        "date_from=2026-10-14",
        "date_from=2026-10-14&date_to=2026-10-14&limit=0",
    ],
)
def test_invalid_history_query(api_client: TestClient, query: str) -> None:
    assert api_client.get(f"/prices/history?ticker=btc_usd&{query}").status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=10001", "offset=-1", "limit=abc"])
def test_invalid_pagination(api_client: TestClient, query: str) -> None:
    assert api_client.get(f"/prices?ticker=btc_usd&{query}").status_code == 422


def test_openapi_requires_ticker_for_every_price_endpoint(api_client: TestClient) -> None:
    paths = api_client.get("/openapi.json").json()["paths"]
    for path in ("/prices", "/prices/latest", "/prices/history"):
        operation = paths[path]["get"]
        ticker = next(p for p in operation["parameters"] if p["name"] == "ticker")
        assert ticker["in"] == "query" and ticker["required"]
        assert "post" not in paths[path]
    assert api_client.post("/prices?ticker=btc_usd").status_code == 405


def test_database_error_is_503_and_does_not_leak_credentials() -> None:
    class UnavailableRepository(MemoryRepository):
        async def latest(self, ticker: Ticker) -> Price | None:
            raise OperationalError("SELECT", {}, Exception("password=secret"))

    app = create_app()
    app.dependency_overrides[get_query_service] = lambda: PriceQueryService(UnavailableRepository())
    with TestClient(app) as client:
        response = client.get("/prices/latest?ticker=btc_usd")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database temporarily unavailable"}
