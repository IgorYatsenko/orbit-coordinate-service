# Orbit Coordinate Service

Прототип микросервиса расчёта координат космических аппаратов.

Текущая версия **0.1.0** содержит инфраструктурное основание: FastAPI, PostgreSQL,
миграции, health API и проверки качества. Расчёт координат появится в версии 0.2.0.

## Запуск

Нужны Docker и Docker Compose. Из корня репозитория:

```bash
docker compose up --build --wait
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
```

Compose запускает PostgreSQL, применяет миграции отдельным контейнером и запускает API.
Успешная команда `--wait` означает, что приложение прошло проверку готовности.
Swagger UI доступен по адресу [localhost:8000/docs](http://localhost:8000/docs).

Пример ответа `/health/ready`:

```json
{"status":"ok","version":"0.1.0","database":"ok"}
```

Настройки по умолчанию позволяют запустить пример сразу. Для изменения параметров:

```bash
cp .env.example .env
```

Отредактируйте `.env` и повторите команду запуска. Приложение и PostgreSQL публикуются
только на `127.0.0.1`. Порты по умолчанию: API `8000`, PostgreSQL `55432`.
Учётные данные в примере предназначены для локальной демонстрации.

```bash
docker compose logs --tail 50 app migrate
docker compose stop
```

`stop` сохраняет рабочие данные PostgreSQL в Docker volume.

## Разработка на Python

Нужны Python 3.13 и Poetry 2.4.1:

```bash
poetry env use python3.13
poetry install
cp .env.example .env
poetry run pre-commit install
docker compose up -d --wait postgres
poetry run poe migrate
poetry run poe start
```

При таком запуске PostgreSQL работает в Docker, приложение — в локальной `.venv`.
`.env.example` уже содержит соответствующие адрес и порт БД.
Для запуска Python-приложения остановите контейнер `app`, если он занимает тот же HTTP-порт.

## Проверки

Быстрые проверки, не требующие БД:

```bash
poetry run poe check
poetry run pre-commit run --all-files
```

Все тесты в Docker с отдельной тестовой PostgreSQL:

```bash
docker compose --profile test run --build --rm tests
```

Все тесты локальной `.venv` с тестовой БД в Docker:

```bash
docker compose --profile test up -d --wait postgres-test
poetry run poe test
```

Тестовая БД использует собственные `APP_TEST_DB_*`, порт `55433` и временное хранилище
в памяти. Тесты не используют рабочий volume `postgres-data`.
Отдельные наборы: `poetry run poe test-unit` и `poetry run poe test-integration`.

Описание проверок и их ограничений: [тестирование](docs/testing.md).

## Устройство и объяснения

- [Архитектура и обоснования](docs/architecture.md): выбранные слои, библиотеки,
  транзакции, запуск ресурсов и рассмотренные альтернативы.
- [Предметная область](docs/domain.md): КА, TLE, OMM, эпоха, SGP4, WGS72/WGS84 и ограничения точности.
- [Настройки](docs/configuration.md): все переменные окружения, приоритеты и начальная конфигурация.
- [История изменений](CHANGELOG.md).

```text
api/router/          HTTP-маршруты и ответы
api/managers/        координация операций
api/services/        PostgreSQL и жизненный цикл ресурсов
api/settings.py      настройки из окружения и .env
models/pydantic/     модели внешних контрактов
models/sqlalchemy/   основание ORM-моделей
migrations/postgres/ миграции Alembic
tests/unit/          проверки без PostgreSQL
tests/integration/   проверки с настоящей PostgreSQL
```

Каталоги доступа к данным и вычислительного ядра появятся вместе с соответствующим кодом.
Версия 0.1.0 ещё не выполняет орбитальные расчёты; примеры запросов TLE/JSON появятся
вместе с endpoint расчёта в 0.2.0.
