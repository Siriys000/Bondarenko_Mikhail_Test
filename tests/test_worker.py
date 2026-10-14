from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from celery.beat import ScheduleEntry
from celery.exceptions import Retry

from price_service.domain import CollectionFailed
from price_service.settings import Settings
from price_service.worker import CollectPricesTask, MinuteSlotScheduler, create_celery_app


def test_celery_schedule_and_registration() -> None:
    app = create_celery_app(Settings())
    assert "prices.collect" in app.tasks
    assert app.conf.timezone == "UTC"
    assert app.conf.task_ignore_result
    assert app.backend.__class__.__name__ == "DisabledBackend"
    entry = app.conf.beat_schedule["collect-index-prices-every-minute"]
    assert entry["task"] == "prices.collect"
    assert entry["schedule"].minute == set(range(60))
    app.close()


def test_worker_preserves_slot_on_retry() -> None:
    task = CollectPricesTask(Settings())
    task.push_request(retries=1)
    try:
        with (
            patch("price_service.worker.collect_prices", new_callable=AsyncMock) as collect,
            patch.object(task, "retry", side_effect=Retry()) as retry,
            patch("price_service.worker.SystemClock.timestamp", return_value=125),
        ):
            collect.side_effect = CollectionFailed("temporary")
            with pytest.raises(Retry):
                task.run()
            collect.assert_awaited_once_with(Settings(), 120)
            assert retry.call_args.kwargs["kwargs"] == {"collection_slot": 120}
            assert retry.call_args.kwargs["countdown"] == 4
    finally:
        task.pop_request()


def test_worker_uses_supplied_slot() -> None:
    with patch("price_service.worker.collect_prices", new_callable=AsyncMock) as collect:
        CollectPricesTask(Settings()).run(collection_slot=60)
    collect.assert_awaited_once_with(Settings(), 60)


def test_invalid_database_driver() -> None:
    with pytest.raises(ValueError, match="postgresql"):
        Settings(database_url="sqlite:///prices.db")


def test_scheduler_stamps_message_and_keeps_schedule_entry_unchanged() -> None:
    entry = ScheduleEntry(
        name="prices",
        task="prices.collect",
        kwargs={"collection_slot": 60},
        last_run_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    scheduler = object.__new__(MinuteSlotScheduler)
    with (
        patch("price_service.worker.SystemClock.timestamp", return_value=185),
        patch("celery.beat.PersistentScheduler.apply_async") as publish,
    ):
        scheduler.apply_async(entry)
    assert publish.call_args.args[0].kwargs == {"collection_slot": 180}
    assert entry.kwargs == {"collection_slot": 60}
