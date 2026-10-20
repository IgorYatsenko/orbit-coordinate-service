from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from api.main import Application
from api.services import Services
from api.services.postgresql import PostgreSQL
from api.settings import _Settings


class _TestSettings(BaseSettings):
    APP_TEST_DB_HOST: str = Field(default="localhost", min_length=1)
    APP_TEST_DB_PORT: int = Field(default=55433, ge=1, le=65535)
    APP_TEST_DB_USER: str = Field(default="orbits_test", min_length=1)
    APP_TEST_DB_PASSWORD: SecretStr = Field(default=SecretStr("orbits_test"))
    APP_TEST_DB_NAME: str = Field(default="orbits_test")

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


@pytest.fixture
async def database(app_settings: _Settings, migrated_database: None) -> AsyncIterator[PostgreSQL]:
    services = Services(config=app_settings)
    await services.database.start()
    try:
        yield services.database
    finally:
        await services.database.stop()


@pytest.fixture
async def client(app_settings: _Settings, migrated_database: None) -> AsyncIterator[httpx.AsyncClient]:
    app = Application(settings=app_settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client
