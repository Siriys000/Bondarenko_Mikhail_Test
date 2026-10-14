from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from price_service.api.schemas import HistoryQuery, PriceQuery, PriceResponse, TickerQuery
from price_service.domain import Price
from price_service.services import PriceQueryService


def get_query_service(request: Request) -> PriceQueryService:
    return cast(PriceQueryService, request.app.state.query_service)


def as_response(price: Price) -> PriceResponse:
    return PriceResponse(ticker=price.ticker, price=price.price, timestamp=price.timestamp)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/prices", tags=["Prices"])

    @router.get("", response_model=list[PriceResponse], summary="All stored prices")
    async def all_prices(
        query: Annotated[PriceQuery, Query()],
        service: Annotated[PriceQueryService, Depends(get_query_service)],
    ) -> list[PriceResponse]:
        prices = await service.all_prices(query.ticker, limit=query.limit, offset=query.offset)
        return [as_response(price) for price in prices]

    @router.get(
        "/latest",
        response_model=PriceResponse,
        summary="Latest stored price",
        responses={404: {"description": "No stored prices for this ticker"}},
    )
    async def latest(
        query: Annotated[TickerQuery, Query()],
        service: Annotated[PriceQueryService, Depends(get_query_service)],
    ) -> PriceResponse:
        return as_response(await service.latest(query.ticker))

    @router.get("/history", response_model=list[PriceResponse], summary="Prices by calendar days")
    async def history(
        query: Annotated[HistoryQuery, Query()],
        service: Annotated[PriceQueryService, Depends(get_query_service)],
    ) -> list[PriceResponse]:
        prices = await service.history(
            query.ticker, query.date_from, query.date_to, limit=query.limit, offset=query.offset
        )
        return [as_response(price) for price in prices]

    return router
