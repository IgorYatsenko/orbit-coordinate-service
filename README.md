# Orbit Coordinate Service

Прототип микросервиса расчёта координат космических аппаратов.

Версия **1.2.3** вычисляет траекторию из TLE или CelesTrak GP JSON, возвращает
широту, долготу и высоту WGS84 и ведёт реестр метаданных КА в PostgreSQL.
Бизнес-операции требуют входа по логину и паролю; Redis ограничивает частоту запросов.

## Quick start

Нужны Docker с Docker Compose. API, его инфраструктура и создание демопользователя
выполняются в контейнерах.
Выполняйте команды из корня репозитория. При первом запуске:

```bash
cp .env.example .env
docker compose up --build --wait
docker compose exec app python -m api.demo_user
curl --fail http://localhost:8000/health/live
curl --fail -i http://localhost:8000/health/ready
curl --fail http://localhost:8000/metrics
```

Compose запускает PostgreSQL и Redis,
применяет миграции отдельным контейнером и запускает API.
Флаг `--wait` заставляет Compose дождаться готовности контейнеров.
Swagger UI доступен по адресу [localhost:8000/docs](http://localhost:8000/docs).

`/health/ready` возвращает пустой ответ: `200`, если все ресурсы доступны,
или `503`, если хотя бы один недоступен. Проверяются PostgreSQL, Redis,
компонент Auth и вычислительный пул. Причина отказа записывается в лог приложения.

`/metrics` открыт для сбора Prometheus: показывает число запросов и время ответа по маршрутам,
методам и HTTP-кодам. Healthcheck и сам сбор метрик в статистику не входят.
Значения появляются после первых запросов к API.
Сбор можно отключить через `APP_METRICS_ENABLED=false`.
Примеры запросов к метрикам и устройство сбора описаны в [архитектуре](docs/architecture.md#12-метрики-prometheus).

Для изменения параметров отредактируйте `.env` и повторите запуск.
API, PostgreSQL и Redis публикуются только на `127.0.0.1`.
Порты по умолчанию: API `8000`, PostgreSQL `55432`, Redis `56379`.
Учётные данные в примере предназначены для локальной демонстрации.

## Гайд по API

### 1. Вход

Quick start создаёт пользователя **`testuser / test-password`**.
Повторный запуск создания демопользователя сохраняет существующую запись и пароль.

1. Откройте [Swagger](http://localhost:8000/docs), раскройте `POST /api/v1/auth/login`.
2. Нажмите **Try it out**, затем **Execute**. Пример уже содержит демонстрационные данные.
3. Скопируйте значение `access_token` из ответа без кавычек.
4. Нажмите **Authorize**, вставьте токен без слова `Bearer`, подтвердите и закройте окно.

Токен действует 15 минут. После истечения срока повторите вход.
Открытой регистрации нет; все пользователи имеют одинаковый доступ к общему реестру.

Для следующих примеров curl получите токен в переменную текущего терминала:

```bash
TOKEN=$(curl --fail-with-body -sS http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"testuser","password":"test-password"}' \
  | docker compose exec -T app python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
curl --fail-with-body -sS http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Причины выбора токенов и поведение лимитов описаны в [доступе и ограничениях](docs/access.md).

### 2. Расчёт координат

После входа в Swagger откройте `POST /api/v1/orbits/coordinates`, выберите пример в списке `Examples`,
нажмите `Try it out`, затем `Execute`. Доступны TLE и CelesTrak GP JSON
с настоящими элементами МКС. Каждый пример возвращает 61 точку.

TLE — две строки орбитальных элементов. Вариант JSON передаёт такие элементы именованными полями.
Эпоха — момент времени, для которого они определены; алгоритм рассчитывает положение до или после него.
Подробные объяснения сокращений и модели находятся в [предметной области](docs/domain.md).

Оба запроса используют сохранённые данные МКС из CelesTrak с эпохой
`2026-10-20T05:01:14.050560Z`. Начало и конец интервала задаются с часовым поясом,
шаг — целым числом от 1 до 60 секунд. Доступ в интернет для расчёта не нужен.

TLE:

```bash
curl --fail-with-body -sS http://localhost:8000/api/v1/orbits/coordinates \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @examples/request-tle.json
```

JSON с орбитальными параметрами:

```bash
curl --fail-with-body -sS http://localhost:8000/api/v1/orbits/coordinates \
  -H "Authorization: Bearer $TOKEN" \
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

По умолчанию допускается до 200000 точек, включая двое суток с шагом 1 секунда
(172801 точка), два одновременных вычисления на HTTP-процесс.
При заполнении пула запрос получает `503`; время ожидания ограничено 60 секундами.
Задача дольше 120 секунд делает пул неготовым: `/health/ready` и новые расчёты возвращают `503`.
Приложение не прекращает её принудительно. После завершения просроченных задач доступ
восстанавливается; если они не завершаются, требуется перезапуск приложения.
Параметры доступны через `APP_COMPUTE_*`, подробности — в [настройках](docs/configuration.md).
[Замеры](docs/benchmarks.md) содержат условия, команды и обоснование конфигурации.

### 3. Реестр КА

`POST /api/v1/satellites` создаёт метаданные, `GET` возвращает страницу списка,
`GET /{id}` читает запись, `PUT /{id}` полностью заменяет её, `DELETE /{id}` удаляет.
Пример создания:

```bash
curl --fail-with-body -sS http://localhost:8000/api/v1/satellites \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"norad_id":25544,"name":"ISS (ZARYA)","international_designator":"1998-067A","launch_date":"1998-11-20"}'
```

NORAD ID уникален. Расчёт не создаёт запись автоматически и не требует предварительной регистрации КА.

В Swagger сохраните `id` из ответа создания, чтобы прочитать, заменить или удалить запись.
`PUT` заменяет метаданные целиком: пропущенные необязательные поля становятся `null`.
Повторное создание того же NORAD ID возвращает `409`. Для просмотра реестра через curl:

```bash
curl --fail-with-body -sS 'http://localhost:8000/api/v1/satellites?limit=10' \
  -H "Authorization: Bearer $TOKEN"
```

### 4. Ошибки и остановка

| Ответ | Причина и действие |
| --- | --- |
| `401 unauthorized` | Токен отсутствует, недействителен или просрочен. Повторите вход и Authorize. |
| `409 satellite_conflict` | NORAD ID уже зарегистрирован. Найдите запись в реестре. |
| `413 request_too_large` | Тело запроса превысило `APP_HTTP_MAX_BODY_BYTES`, по умолчанию 16 КиБ. |
| `422` | Поля или орбита не прошли проверку. Причина указана в `detail`; используйте готовые Examples. |
| `429 rate_limit_exceeded` | Квота исчерпана. Подождите число секунд из заголовка `Retry-After`. |
| `503 compute_busy` | Все вычислители заняты. Повторите запрос после завершения текущих расчётов. |
| `500 internal_error` | Внутренняя ошибка работы с БД. Проверьте логи приложения; повтор запроса не гарантирует исправления. |
| Другой `503` | Проверьте `/health/ready` и `docker compose logs --tail 50 app postgres redis`. |

`docker compose stop` останавливает окружение и сохраняет реестр и демопользователя.
Для повторного запуска достаточно `docker compose up --build --wait`.
Счётчики лимитов Redis временные и сбрасываются при его перезапуске.
Если порт занят, измените его в `.env`; назначение всех `APP_*` описано в [настройках](docs/configuration.md).

## Разработка на Python

Локальный Python-запуск рассчитан на Linux и macOS: вычислительный процесс использует
модуль `resource`, недоступный в Python для Windows. На Windows используйте Docker
с Linux-контейнерами по quick start выше.

Для локальной разработки нужны Python 3.13 и Poetry 2.4.1:

```bash
poetry env use python3.13
poetry install
cp .env.example .env
poetry run pre-commit install
docker compose up -d --wait postgres redis
poetry run poe migrate
poetry run poe add-test-user
poetry run poe start
```

При таком запуске PostgreSQL и Redis работают в Docker, приложение — в окружении Poetry.
`.env.example` уже содержит соответствующие адрес и порт БД.
Для запуска Python-приложения остановите контейнер `app`, если он занимает тот же HTTP-порт.

Poetry может хранить окружение в общем кэше или в `.venv` проекта. После установки
узнайте путь к его Python:

```bash
poetry env info --executable
```

В PyCharm выберите этот файл как существующий интерпретатор проекта. Если в проекте
есть `.venv`, отметьте её как `Mark Directory As → Excluded`, а для поиска выбирайте
область `Project Files`. Настройки IDE остаются локальными и не включаются в репозиторий.

## Проверки

Быстрые проверки, не требующие БД:

```bash
poetry run poe check
poetry run pre-commit run --all-files
```

Все тесты в Docker с отдельными тестовыми PostgreSQL и Redis:

```bash
docker compose --profile test run --build --rm tests
```

Все тесты в окружении Poetry с тестовой БД в Docker:

```bash
docker compose --profile test up -d --wait postgres-test redis-test
poetry run poe test
```

Тестовая БД использует собственные `APP_TEST_DB_*`, порт `55433` и временное хранилище
в памяти. Redis тестов использует порт `56380`, отдельный контейнер, DB 15 и уникальные ключи.
Тесты не используют рабочий volume `postgres-data` и рабочие счётчики лимитов.
Отдельные наборы: `poetry run poe test-unit` и `poetry run poe test-integration`.

Описание проверок и их ограничений: [тестирование](docs/testing.md).

## Устройство и объяснения

- [Архитектура и обоснования](docs/architecture.md): выбранные слои, библиотеки,
  транзакции, запуск ресурсов и рассмотренные альтернативы.
- [Предметная область](docs/domain.md): КА, TLE, OMM, эпоха, SGP4, WGS72/WGS84 и ограничения точности.
- [Настройки](docs/configuration.md): все переменные окружения, приоритеты и выбранная конфигурация.
- [Доступ и ограничения](docs/access.md): пароли, токены, Redis и альтернативы.
- [Контракт расчёта](docs/api.md): запросы, ответы и ошибки.
- [Замеры](docs/benchmarks.md): воспроизводимые результаты и границы их применимости.
- [История изменений](CHANGELOG.md).

```text
api/router/          HTTP-маршруты и ответы
api/managers/        координация операций
api/services/        PostgreSQL, Redis, Auth, метрики, вычислительный пул и lifecycle
api/db/              SQL-запросы с переданной сессией
api/orbits/          численное ядро и процесс вычисления
api/settings.py      настройки из окружения и .env
models/pydantic/     модели внешних контрактов
models/sqlalchemy/   ORM-модели пользователей и спутников
migrations/postgres/ миграции Alembic
tests/unit/          проверки без PostgreSQL
tests/integration/   проверки с настоящими PostgreSQL, Redis и процессами
examples/            готовые запросы TLE и JSON
benchmarks/          ручные замеры ядра и HTTP
```

`OrbitCalculator` хранит таблицы времени и размер порции, `CalculationWorker` владеет
одним вычислителем в дочернем процессе. Модели результата и отчётов находятся в
`models/pydantic`, настройки benchmark — в `benchmarks/settings.py`.

## Лицензия

Код проекта распространяется по лицензии [MIT](LICENSE).
Сторонние зависимости сохраняют собственные лицензии.
