# Orbit Coordinate Service

English | [Русский](README.ru.md)

A Python backend prototype for calculating satellite positions and managing satellite
metadata. Originally built as a take-home assignment, it demonstrates async API design,
bounded CPU execution, explicit resource ownership and numerical verification.

Version **1.2.3** accepts TLE (two-line orbital elements) or CelesTrak GP JSON and returns
a time series of latitude, longitude and altitude relative to the WGS84 ellipsoid.
PostgreSQL stores the satellite registry. Calculation requests are independent of registry
entries and use the orbital elements supplied by the caller.

**Stack** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 / asyncpg, PostgreSQL, Redis,
Skyfield, sgp4 and NumPy. Docker Compose provides a reproducible local environment.

## Design decisions

- **Bounded CPU execution.** Orbit calculations run in a process pool outside the API
  event loop. An execution slot stays occupied until the underlying job finishes,
  even if the HTTP request times out or is cancelled. Saturation returns `503 compute_busy`.
  HTTP cancellation does not forcibly terminate a running calculation.
- **Explicit transaction and resource ownership.** The database session context owns
  commit and rollback. CPU calculations do not hold database transactions open.
  FastAPI lifespan manages startup and shutdown of database connections, Redis, auth
  resources and the compute pool.
- **Clear component boundaries.** Routers define HTTP contracts, managers coordinate
  operations, and services own infrastructure resources. The numerical core is independent
  of HTTP and PostgreSQL.
- **Controlled access and observability.** Protected endpoints use bearer tokens.
  Redis enforces rate limits. Liveness, dependency readiness and Prometheus metrics
  are exposed separately.
- **Reproducible numerical checks.** Tests use captured orbital inputs, SGP4 reference
  vectors and independent coordinate checks. These verify the implementation of the
  chosen model. Real-world prediction accuracy still depends on the age and quality
  of the orbital elements.

Useful code entry points are [compute admission and lifecycle](api/services/compute.py),
[transaction ownership](api/services/postgresql.py), [resource lifecycle](api/services/services.py)
and the [numerical core](api/orbits/).
Detailed [architecture decisions](docs/architecture.md) and [benchmarks](docs/benchmarks.md)
are available in Russian.

## Quick start

Requires Docker with Docker Compose. Run the commands from the repository root.
On the first run, create a local configuration from the example.

```bash
cp .env.example .env
docker compose up --build --wait
docker compose exec app python -m api.demo_user
curl --fail http://localhost:8000/health/live
curl --fail -i http://localhost:8000/health/ready
```

Compose starts PostgreSQL and Redis, applies migrations in a separate container,
and starts the API. Swagger UI is available at [localhost:8000/docs](http://localhost:8000/docs).
Readiness returns an empty `200` response when PostgreSQL, Redis, auth and the compute
pool are ready, or `503` when a resource is unavailable. Metrics are at
[localhost:8000/metrics](http://localhost:8000/metrics).

The demo login is `testuser` / `test-password`. Re-running the demo-user command keeps
an existing user and password. The example credentials are for local use. Published
ports bind to `127.0.0.1` by default.

## Try the API

Log in and capture the access token. The command uses Python inside the app container,
so no local Python installation is required.

```bash
TOKEN=$(curl --fail-with-body -sS http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"testuser","password":"test-password"}' \
  | docker compose exec -T app python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')

curl --fail-with-body -sS http://localhost:8000/api/v1/orbits/coordinates \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @examples/request-tle.json
```

The sample returns 61 points from a captured ISS orbit. Each point contains `time`,
`latitude_deg`, `longitude_deg` and `altitude_km`. Altitude is in kilometres above the
WGS84 ellipsoid. Replace the input file with [examples/request-omm.json](examples/request-omm.json)
to use the JSON format. Both examples work without external network access for the calculation.

Tokens expire after 15 minutes. In Swagger, call `POST /api/v1/auth/login`, copy
`access_token`, and paste it into **Authorize** without the `Bearer` prefix.
The satellite registry supports create, list, read, replace and delete operations under
`/api/v1/satellites`. All users share the same registry. Duplicate NORAD IDs return `409`.

By default, a request can contain up to 200,000 points, with two concurrent calculations
per HTTP process. The HTTP wait is limited to 60 seconds. A job running beyond 120 seconds
makes the pool unready until overdue work finishes. A permanently stuck job requires
an application restart. Limits are configurable through `APP_COMPUTE_*`.

## Development and tests

For local Python development, use Python 3.13 and Poetry 2.4.1 on Linux or macOS.
On Windows, use Linux containers. Fast checks run without PostgreSQL or Redis.

```bash
poetry env use python3.13
poetry install
poetry run poe check
```

This runs Ruff lint and format checks, ty and unit tests. To run the full test suite
with dedicated test PostgreSQL and Redis containers, use Docker Compose.

```bash
docker compose --profile test run --build --rm tests
```

Tests cover request validation, overload and cancellation, numerical results,
transaction rollback, concurrent uniqueness conflicts and migrations.
[CI](.github/workflows/ci.yml) also starts the application and checks the example
requests through a real HTTP server. Test services are separate from the demo data store.

## Further documentation

The detailed guides below are in Russian. Code, docstrings and OpenAPI descriptions
are in English.

- [Full setup and API walkthrough](README.ru.md)
- [Architecture and alternatives](docs/architecture.md)
- [Orbital model and accuracy limits](docs/domain.md)
- [API contract](docs/api.md)
- [Configuration](docs/configuration.md)
- [Authentication and rate limits](docs/access.md)
- [Testing and verification scope](docs/testing.md)
- [Benchmark methodology and results](docs/benchmarks.md)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses.
