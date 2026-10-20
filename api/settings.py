from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class _Settings(BaseSettings):
    """Validated runtime configuration shared by the API and migration CLI."""

    APP_HOST: str = Field(default="0.0.0.0", min_length=1, description="HTTP listen address.")
    APP_PORT: int = Field(default=8000, ge=1, le=65535, description="HTTP listen port.")
    APP_ROOT_PATH: str = Field(default="", description="External reverse-proxy path prefix.")
    APP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Application and HTTP server log level."
    )
    APP_DOCS_ENABLED: bool = Field(default=True, description="Expose OpenAPI and Swagger UI.")
    APP_HTTP_WORKERS: int = Field(default=1, ge=1, description="HTTP server process count.")
    APP_HTTP_KEEP_ALIVE_SEC: int = Field(default=5, ge=1, description="Idle HTTP connection timeout in seconds.")
    APP_SHUTDOWN_TIMEOUT_SEC: int = Field(default=15, ge=1, description="HTTP request shutdown deadline in seconds.")

    APP_DB_HOST: str = Field(default="localhost", min_length=1, description="PostgreSQL hostname.")
    APP_DB_PORT: int = Field(default=55432, ge=1, le=65535, description="PostgreSQL connection port.")
    APP_DB_USER: str = Field(default="orbits", min_length=1, description="PostgreSQL username.")
    APP_DB_PASSWORD: SecretStr = Field(default=SecretStr("orbits"), description="PostgreSQL password.")
    APP_DB_NAME: str = Field(default="orbits", min_length=1, description="PostgreSQL database name.")
    APP_DB_POOL_SIZE: int = Field(default=5, ge=1, description="Persistent connections per HTTP process.")
    APP_DB_MAX_OVERFLOW: int = Field(default=0, ge=0, description="Additional temporary connections per HTTP process.")
    APP_DB_POOL_TIMEOUT_SEC: float = Field(default=5.0, gt=0, description="Connection pool acquisition timeout.")
    APP_DB_CONNECT_TIMEOUT_SEC: float = Field(default=5.0, gt=0, description="New database connection timeout.")
    APP_DB_STATEMENT_TIMEOUT_SEC: float = Field(default=5.0, ge=0.001, description="PostgreSQL statement timeout.")
    APP_DB_HEALTHCHECK_TIMEOUT_SEC: float = Field(default=2.0, gt=0, description="Total database healthcheck timeout.")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True)

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.APP_DB_USER,
            password=self.APP_DB_PASSWORD.get_secret_value(),
            host=self.APP_DB_HOST,
            port=self.APP_DB_PORT,
            database=self.APP_DB_NAME,
        )


@lru_cache
def get_settings() -> _Settings:
    return _Settings()
