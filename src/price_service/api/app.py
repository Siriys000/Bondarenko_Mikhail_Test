import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from price_service.api.routes import create_router
from price_service.domain import PriceNotFound
from price_service.infrastructure.database import SqlAlchemyPriceRepository
from price_service.services import PriceQueryService
from price_service.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    logger = logging.getLogger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(configuration.database_url, pool_pre_ping=True)
        repository = SqlAlchemyPriceRepository(async_sessionmaker(engine, expire_on_commit=False))
        app.state.query_service = PriceQueryService(repository)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Deribit index prices", version="1.0.0", lifespan=lifespan)
    app.include_router(create_router())

    @app.exception_handler(PriceNotFound)
    async def price_not_found(request: Request, exc: PriceNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database operation failed", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})

    return app
