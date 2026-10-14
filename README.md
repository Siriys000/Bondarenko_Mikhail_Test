# Deribit Price Service

Сервис каждую минуту получает index price `btc_usd` и `eth_usd` с Deribit,
сохраняет цену и UNIX timestamp в PostgreSQL и предоставляет GET API на FastAPI.

**Стек:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, aiohttp, Celery Beat/Worker, Redis, PostgreSQL.

## Запуск

```bash
cp .env.example .env
docker compose up --build -d
```

В PowerShell вместо `cp` можно использовать `Copy-Item .env.example .env`.
Миграции применяются автоматически перед запуском приложения.
Первый сбор происходит на следующей минутной границе UTC.

Swagger UI: [localhost:8000/docs](http://localhost:8000/docs).

## API

| GET | Назначение |
| --- | --- |
| `/prices?ticker=btc_usd` | Все сохранённые записи |
| `/prices/latest?ticker=eth_usd` | Последняя сохранённая цена |
| `/prices/history?ticker=btc_usd&date_from=2026-10-14&date_to=2026-10-14` | История за календарные дни UTC, включительно |

`ticker` обязателен в каждом методе. История поддерживает `limit` и `offset`;
без `limit` возвращаются все записи. Цена в JSON — десятичная строка, время — UNIX seconds.

## Проверки

```bash
uv sync --frozen --python 3.12
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

CI также проверяет миграции, репозиторий на PostgreSQL и сборку Docker.

## Документация

- [Развёртывание и разработка](docs/deployment.md)
- [Архитектура и схема](docs/architecture.md)
- [Контракт API](docs/api.md)

## Design decisions

Обоснование архитектуры, идемпотентности, обработки ошибок и хранения данных:
[Design decisions](docs/design-decisions.md).
