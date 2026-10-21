import httpx
import pytest
from asyncpg import (
    CannotConnectNowError,
    ConnectionDoesNotExistError,
    LockNotAvailableError,
    PostgresError,
    QueryCanceledError,
    TooManyConnectionsError,
    UndefinedColumnError,
    UniqueViolationError,
)
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from api.db.errors import is_database_unavailable
from api.main import Application
from api.settings import _Settings
from models.exceptions.infrastructure import DatabaseUnavailable


@pytest.mark.parametrize(
    ("error", "unavailable"),
    [
        (PoolTimeoutError(), True),
        (DBAPIError(None, None, RuntimeError(), connection_invalidated=True), True),
        (TooManyConnectionsError(), True),
        (CannotConnectNowError(), True),
        (ConnectionDoesNotExistError(), True),
        (QueryCanceledError(), True),
        (LockNotAvailableError(), True),
        (UniqueViolationError(), False),
        (UndefinedColumnError(), False),
        (PostgresError(), False),
        (ProgrammingError(None, None, RuntimeError()), False),
    ],
)
def test_only_availability_failures_are_retryable(error: SQLAlchemyError | PostgresError, unavailable: bool) -> None:
    assert is_database_unavailable(error) is unavailable


@pytest.mark.parametrize("error_type", [ProgrammingError, IntegrityError])
async def test_unexpected_database_errors_return_500_and_log_only_safe_stack_locations(
    caplog: pytest.LogCaptureFixture, error_type: type[SQLAlchemyError]
) -> None:
    private = "sensitive-sql-parameter-do-not-log"
    error = error_type("SELECT private_query", {"password": private}, RuntimeError(private))
    app = Application(settings=_Settings())

    @app.get("/failed-query")
    async def fail_sql() -> None:
        raise error

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/failed-query")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert "fail_sql" in caplog.text and error_type.__name__ in caplog.text
    assert private not in caplog.text + response.text
    assert "SELECT private_query" not in caplog.text + response.text


async def test_database_unavailability_preserves_the_503_contract() -> None:
    app = Application(settings=_Settings())

    @app.get("/unavailable-database")
    async def unavailable() -> None:
        raise DatabaseUnavailable()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/unavailable-database")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
