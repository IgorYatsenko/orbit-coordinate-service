from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from api.main import Application
from api.services import Services
from api.services.postgresql import PostgreSQL
from api.settings import _Settings
from dev.project_user import create_user_setup
from models.pydantic.auth import LoginRequest


class _TestSettings(BaseSettings):
    APP_TEST_DB_HOST: str = Field(default="localhost", min_length=1)
    APP_TEST_DB_PORT: int = Field(default=55433, ge=1, le=65535)
    APP_TEST_DB_USER: str = Field(default="orbits_test", min_length=1)
    APP_TEST_DB_PASSWORD: SecretStr = Field(default=SecretStr("orbits_test"))
    APP_TEST_DB_NAME: str = Field(default="orbits_test")
    APP_TEST_REDIS_HOST: str = Field(default="localhost", min_length=1)
    APP_TEST_REDIS_PORT: int = Field(default=56380, ge=1, le=65535)
    APP_TEST_REDIS_PASSWORD: SecretStr = Field(default=SecretStr("orbits_redis_test"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("APP_TEST_DB_NAME")
    @classmethod
    def require_test_database(cls, value: str) -> str:
        if not value.endswith("_test"):
            raise ValueError("Integration tests require an explicit database ending in '_test'")
        return value


@pytest.fixture
def app_settings() -> _Settings:
    settings = _TestSettings()
    return _Settings(
        APP_DB_HOST=settings.APP_TEST_DB_HOST,
        APP_DB_PORT=settings.APP_TEST_DB_PORT,
        APP_DB_USER=settings.APP_TEST_DB_USER,
        APP_DB_PASSWORD=settings.APP_TEST_DB_PASSWORD,
        APP_DB_NAME=settings.APP_TEST_DB_NAME,
        APP_DB_POOL_SIZE=2,
        APP_DB_MAX_OVERFLOW=0,
        APP_AUTH_TOKEN_SECRET=SecretStr("integration-test-secret-for-token-signing-only"),
        APP_REDIS_HOST=settings.APP_TEST_REDIS_HOST,
        APP_REDIS_PORT=settings.APP_TEST_REDIS_PORT,
        APP_REDIS_PASSWORD=settings.APP_TEST_REDIS_PASSWORD,
        APP_REDIS_DB=15,
        APP_REDIS_KEY_PREFIX=f"test:{uuid4()}",
    )


@pytest.fixture
def migration_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


@pytest.fixture
async def engine(app_settings: _Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(app_settings.database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_database(engine: AsyncEngine, migration_config: Config) -> None:
    def upgrade(connection: Connection) -> None:
        migration_config.attributes["connection"] = connection
        command.upgrade(migration_config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(upgrade)
        await connection.execute(text("TRUNCATE TABLE satellites, users"))


@pytest.fixture
async def database(app_settings: _Settings, migrated_database: None) -> AsyncIterator[PostgreSQL]:
    services = Services(config=app_settings)
    await services.database.start()
    try:
        yield services.database
    finally:
        await services.database.stop()


@pytest.fixture
async def application(app_settings: _Settings, migrated_database: None) -> AsyncIterator[Application]:
    app = Application(settings=app_settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def anonymous_client(application: Application) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client


@pytest.fixture
def user_credentials() -> LoginRequest:
    return LoginRequest(username="reviewer", password="test-password-not-for-real-use")


@pytest.fixture
async def registered_user(application: Application, user_credentials: LoginRequest) -> None:
    assert await create_user_setup(services=application.services, credentials=user_credentials)


@pytest.fixture
async def client(
    anonymous_client: httpx.AsyncClient, registered_user: None, user_credentials: LoginRequest
) -> httpx.AsyncClient:
    response = await anonymous_client.post(
        "/api/v1/auth/login",
        json={"username": user_credentials.username, "password": user_credentials.password.get_secret_value()},
    )
    assert response.status_code == 200, response.text
    anonymous_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return anonymous_client
