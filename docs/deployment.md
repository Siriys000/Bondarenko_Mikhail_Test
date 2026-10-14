# Развёртывание и разработка

## Docker Compose

Нужны Git, Docker Engine/Desktop с Linux-контейнерами и Docker Compose v2.
Python на хосте для контейнерного запуска не требуется.

```bash
git clone https://github.com/Siriys000/Bondarenko_Mikhail_Test.git
cd Bondarenko_Mikhail_Test
cp .env.example .env
docker compose up --build -d
docker compose ps -a
docker compose logs -f api worker beat migrate
```

В PowerShell: `Copy-Item .env.example .env`.
Сервис `migrate` должен завершиться с кодом 0; это нормальное состояние.
Если он завершился с ошибкой, посмотрите `docker compose logs migrate`.
Первый сбор выполняется на следующей минутной границе; до него `/prices` возвращает `[]`.

```bash
curl "http://localhost:8000/prices?ticker=btc_usd"
curl "http://localhost:8000/prices/latest?ticker=eth_usd"
curl "http://localhost:8000/prices/history?ticker=btc_usd&date_from=2026-10-14&date_to=2026-10-14"
```

В PowerShell можно использовать `Invoke-RestMethod` с теми же URL.
Swagger UI доступен на `http://localhost:8000/docs`.

Остановка с сохранением цен: `docker compose down`.
Повторный запуск после изменения кода: `docker compose up --build -d`.
PostgreSQL использует named volume, сохраняющийся при обычной остановке.
Одновременно должен работать только один экземпляр Beat.

## Настройки

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `POSTGRES_USER` | `prices` | Пользователь БД в Compose |
| `POSTGRES_PASSWORD` | `prices_local` | Пароль для локальной разработки |
| `POSTGRES_DB` | `prices` | База приложения |
| `POSTGRES_PORT` | `5432` | Опубликованный порт БД |
| `REDIS_PORT` | `6379` | Опубликованный порт Redis |
| `API_PORT` | `8000` | Опубликованный порт API |
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5432/prices` | Подключение при запуске Python на хосте |
| `REDIS_URL` | `redis://localhost:6379/0` | Брокер при запуске Python на хосте |
| `DERIBIT_BASE_URL` | `https://www.deribit.com/api/v2` | Адрес Deribit |
| `HTTP_TIMEOUT_SECONDS` | `10` | Таймаут одного запроса |
| `COLLECTION_MAX_RETRIES` | `3` | Повторы после первоначальной попытки |

Compose формирует собственные `DATABASE_URL` и `REDIS_URL` с DNS-именами сервисов;
значения с `localhost` предназначены для локального запуска Python.
При занятых портах измените `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT` в `.env`.
Для локального Python также обновите порты в `DATABASE_URL` и `REDIS_URL`.
При нестандартных символах в пароле используйте URL-кодирование в URL подключения.
Изменение пароля в `.env` не меняет пароль уже инициализированного PostgreSQL volume.

## Запуск Python на хосте

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync --frozen --python 3.12
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn price_service.api.app:create_app --factory --reload
```

В отдельных терминалах:

```bash
uv run python -m price_service.worker worker --loglevel=INFO
uv run python -m price_service.worker beat --loglevel=INFO
```

Celery prefork предназначен для Linux. Для разработки на Windows используйте
`worker --loglevel=INFO --pool=solo`; основной способ запуска Worker — Docker.

## Миграции

```bash
uv run alembic upgrade head
uv run alembic check
uv run alembic revision --autogenerate -m "describe schema change"
```

Перед применением сгенерированной миграции проверьте её содержимое.
Для проверки первоначальной миграции в изолированной тестовой БД можно выполнить
`alembic downgrade base`, затем снова `alembic upgrade head`.
Downgrade удаляет таблицу цен, поэтому его нельзя выполнять на БД с нужными данными.

## Тесты и статические проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not integration" --cov
```

Тесты API и клиента не требуют PostgreSQL или реальной биржи.
Без `TEST_DATABASE_URL` интеграционные проверки явно пропускаются.
Для полного прогона создайте отдельную БД, примените миграции и задайте обе переменные:

```bash
docker compose exec -T postgres createdb -U prices prices_test
export DATABASE_URL=postgresql+asyncpg://prices:prices_local@localhost:5432/prices_test
export TEST_DATABASE_URL="$DATABASE_URL"
uv run alembic upgrade head
uv run alembic check
uv run pytest --cov --cov-fail-under=85
```

В PowerShell вместо `export`:

```powershell
$env:DATABASE_URL = 'postgresql+asyncpg://prices:prices_local@localhost:5432/prices_test'
$env:TEST_DATABASE_URL = $env:DATABASE_URL
```

Интеграционные тесты очищают таблицу `prices` в `TEST_DATABASE_URL`.
Используйте только отдельную тестовую БД. Создавать БД повторно при каждом прогоне не нужно.
GitHub Actions автоматически создаёт изолированный PostgreSQL, применяет миграцию,
проверяет схему, Ruff, mypy, тесты с покрытием и Docker build.
