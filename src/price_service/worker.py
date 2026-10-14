"""Celery composition and CLI, without a module-level application or connection."""

import asyncio
import copy
import logging
import sys
from typing import Any

import aiohttp
from celery import Celery, Task
from celery.beat import PersistentScheduler
from celery.schedules import crontab
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from price_service.domain import CollectionFailed
from price_service.infrastructure.database import SqlAlchemyPriceRepository
from price_service.infrastructure.deribit import DeribitClient
from price_service.services import PriceCollector, SystemClock
from price_service.settings import Settings


class MinuteSlotScheduler(PersistentScheduler):  # type: ignore[misc]
    """Stamp the minute in the message before publication, also covering redelivery."""

    def apply_async(self, entry: Any, producer: Any = None, advance: bool = True) -> Any:
        stamped_entry = copy.copy(entry)
        if entry.task == CollectPricesTask.name:
            now = SystemClock().timestamp()
            stamped_entry.kwargs = {**entry.kwargs, "collection_slot": now - now % 60}
        return super().apply_async(stamped_entry, producer=producer, advance=advance)


async def collect_prices(settings: Settings, collection_slot: int) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        repository = SqlAlchemyPriceRepository(async_sessionmaker(engine, expire_on_commit=False))
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            collector = PriceCollector(
                repository, DeribitClient(session, settings.deribit_base_url), SystemClock()
            )
            await collector.collect(collection_slot)
    finally:
        await engine.dispose()


class CollectPricesTask(Task):  # type: ignore[misc]
    name = "prices.collect"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self, collection_slot: int | None = None) -> None:
        slot = collection_slot
        if slot is None:
            now = SystemClock().timestamp()
            slot = now - now % 60
        try:
            asyncio.run(collect_prices(self._settings, slot))
        except (CollectionFailed, OperationalError) as exc:
            # Preserve the original slot on retries, including retries crossing a minute boundary.
            raise self.retry(
                exc=exc,
                kwargs={"collection_slot": slot},
                countdown=min(2 ** (self.request.retries + 1), 30),
                max_retries=self._settings.collection_max_retries,
            ) from exc


def create_celery_app(settings: Settings | None = None) -> Celery:
    configuration = settings if settings is not None else Settings()
    app = Celery("price_service", broker=configuration.redis_url, set_as_current=False)
    app.conf.update(
        timezone="UTC",
        enable_utc=True,
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        beat_scheduler="price_service.worker:MinuteSlotScheduler",
        beat_schedule={
            "collect-index-prices-every-minute": {
                "task": CollectPricesTask.name,
                "schedule": crontab(minute="*"),
                "options": {"expires": 55},
            }
        },
    )
    app.register_task(CollectPricesTask(configuration))
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if len(sys.argv) < 2 or sys.argv[1] not in ("worker", "beat"):
        raise SystemExit("Usage: python -m price_service.worker {worker|beat} [celery options]")
    app = create_celery_app()
    app.start(sys.argv[1:])


if __name__ == "__main__":
    main()
