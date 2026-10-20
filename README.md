# Orbit Coordinate Service

Прототип микросервиса расчёта координат космических аппаратов.

Текущая версия **0.2.1** вычисляет траекторию из TLE или CelesTrak GP JSON и возвращает
широту, долготу и высоту WGS84. Реестр КА, вход пользователей и ограничения запросов
появятся в версии 0.3.0.

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
{"status":"ok","version":"0.2.1","database":"ok","compute":"ok"}
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

## Расчёт координат

В Swagger откройте `POST /api/v1/orbits/coordinates`, выберите пример в списке `Examples`,
нажмите `Try it out`, затем `Execute`. Доступны рабочие варианты TLE и CelesTrak GP JSON;
строковые заглушки заменены настоящими элементами МКС. Каждый пример возвращает 61 точку.

Оба запроса используют сохранённые данные МКС из CelesTrak с эпохой
`2026-10-20T05:01:14.050560Z`. Начало и конец интервала задаются с часовым поясом,
шаг — целым числом от 1 до 60 секунд. Доступ в интернет для расчёта не нужен.

TLE:

```bash
curl --fail-with-body -sS http://localhost:8000/api/v1/orbits/coordinates \
  -H 'Content-Type: application/json' --data-binary @examples/request-tle.json
```

JSON с орбитальными параметрами:

```bash
curl --fail-with-body -sS http://localhost:8000/api/v1/orbits/coordinates \
  -H 'Content-Type: application/json' --data-binary @examples/request-omm.json
```

Ответ содержит `norad_id`, `epoch`, `reference_frame`, параметры сетки и массив `points`.
Каждая точка содержит `time`, `latitude_deg`, `longitude_deg`, `altitude_km`.
Высота измеряется в километрах над эллипсоидом WGS84.
Полный [контракт API](docs/api.md) объясняет оба формата, ошибки, UTC и правила границ.
Источники и контрольные суммы входных данных находятся в [тестовых данных](tests/fixtures/README.md).

Свежие элементы можно получить явно:

```bash
curl --fail -sS 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE'
curl --fail -sS 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=JSON'
```

В первом случае две строки переносятся в `orbit.line1` и `orbit.line2`,
во втором один объект массива — в `orbit.elements`. Устаревшие элементы постепенно
теряют достоверность; отсутствие ошибки расчёта не обещает точного положения реального КА.

По умолчанию допускается до 100000 точек, два одновременных вычисления на HTTP-процесс.
При заполнении пула запрос получает `503`; время ожидания ограничено 30 секундами.
Параметры доступны через `APP_COMPUTE_*`, подробности — в [настройках](docs/configuration.md).
Первые [замеры](docs/benchmarks.md) содержат условия, команды и ограничения результатов.

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

В PyCharm отметьте `.venv` как `Mark Directory As → Excluded`, а для поиска выбирайте
область `Project Files`. Настройки IDE остаются локальными и не включаются в репозиторий.

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
- [Контракт расчёта](docs/api.md): запросы, ответы и ошибки.
- [Замеры](docs/benchmarks.md): воспроизводимые начальные результаты.
- [История изменений](CHANGELOG.md).

```text
api/router/          HTTP-маршруты и ответы
api/managers/        координация операций
api/services/        PostgreSQL, вычислительный пул и жизненный цикл ресурсов
api/orbits/          численное ядро и процесс вычисления
api/settings.py      настройки из окружения и .env
models/pydantic/     модели внешних контрактов
models/sqlalchemy/   основание ORM-моделей
migrations/postgres/ миграции Alembic
tests/unit/          проверки без PostgreSQL
tests/integration/   проверки с настоящей PostgreSQL
examples/            готовые запросы TLE и JSON
benchmarks/          ручные замеры ядра и HTTP
```

Каталог доступа к данным появится вместе с реестром в 0.3.0.

`OrbitCalculator` хранит таблицы времени и размер порции, `CalculationWorker` владеет
одним вычислителем в дочернем процессе. Модели результата и отчётов находятся в
`models/pydantic`, настройки benchmark — в `benchmarks/settings.py`.
