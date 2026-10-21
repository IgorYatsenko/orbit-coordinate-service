from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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
    APP_HTTP_TRUSTED_PROXY_IPS: str = Field(
        default="", description="Trusted proxy IPs/CIDRs; empty disables proxy headers."
    )
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

    APP_AUTH_TOKEN_SECRET: SecretStr = Field(
        min_length=32, description="Shared HS256 signing secret, at least 32 characters."
    )
    APP_AUTH_TOKEN_TTL_SEC: int = Field(default=900, ge=1, description="Access token lifetime in seconds.")
    APP_AUTH_TOKEN_ISSUER: str = Field(default="orbit-coordinate-service", min_length=1, description="JWT issuer.")
    APP_AUTH_TOKEN_AUDIENCE: str = Field(default="orbit-api", min_length=1, description="JWT audience.")
    APP_AUTH_PASSWORD_WORKERS: int = Field(default=2, ge=1, description="Concurrent password checks per HTTP process.")
    APP_AUTH_PASSWORD_MEMORY_KIB: int = Field(default=65536, ge=8, description="Argon2 memory per password operation.")
    APP_AUTH_PASSWORD_TIME_COST: int = Field(default=3, ge=1, description="Argon2 iteration count.")
    APP_AUTH_PASSWORD_PARALLELISM: int = Field(default=2, ge=1, description="Argon2 lanes per password operation.")

    APP_REDIS_HOST: str = Field(default="localhost", min_length=1, description="Rate limiter Redis hostname.")
    APP_REDIS_PORT: int = Field(default=56379, ge=1, le=65535, description="Redis connection port.")
    APP_REDIS_DB: int = Field(default=0, ge=0, le=15, description="Redis logical database.")
    APP_REDIS_PASSWORD: SecretStr = Field(default=SecretStr("orbits_redis"), description="Redis password.")
    APP_REDIS_KEY_PREFIX: str = Field(
        default="orbits", min_length=1, max_length=100, description="Rate limit key namespace."
    )
    APP_REDIS_MAX_CONNECTIONS: int = Field(default=20, ge=1, description="Redis connections per HTTP process.")
    APP_REDIS_CONNECT_TIMEOUT_SEC: float = Field(default=2.0, gt=0, description="Redis connection timeout.")
    APP_REDIS_SOCKET_TIMEOUT_SEC: float = Field(default=2.0, gt=0, description="Redis command timeout.")
    APP_REDIS_HEALTHCHECK_TIMEOUT_SEC: float = Field(default=2.0, gt=0, description="Total Redis healthcheck timeout.")
    APP_RATE_LIMIT_USER_REQUESTS: int = Field(default=60, ge=1, description="Protected requests per user window.")
    APP_RATE_LIMIT_USER_WINDOW_SEC: int = Field(default=60, ge=1, description="Per-user rate limit window.")
    APP_RATE_LIMIT_LOGIN_REQUESTS: int = Field(default=10, ge=1, description="Login attempts per client IP window.")
    APP_RATE_LIMIT_LOGIN_WINDOW_SEC: int = Field(default=60, ge=1, description="Login rate limit window.")

    APP_COMPUTE_WORKERS: int = Field(default=2, ge=1, description="Calculation processes per HTTP process.")
    APP_COMPUTE_MAX_POINTS: int = Field(default=200_000, ge=1, description="Maximum trajectory points per request.")
    APP_COMPUTE_CHUNK_POINTS: int = Field(default=1024, ge=1, description="Vectorized points per calculation chunk.")
    APP_COMPUTE_NUMERIC_THREADS: int = Field(
        default=1, ge=1, description="BLAS/OpenMP threads per calculation process."
    )
    APP_COMPUTE_TIMEOUT_SEC: float = Field(default=60.0, gt=0, description="HTTP wait deadline for a calculation.")
    APP_COMPUTE_START_TIMEOUT_SEC: float = Field(default=30.0, gt=0, description="Calculation pool warmup deadline.")
    APP_COMPUTE_HEALTHCHECK_TIMEOUT_SEC: float = Field(default=2.0, gt=0, description="Idle pool probe deadline.")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True)

    @model_validator(mode="after")
    def validate_password_memory(self) -> Self:
        if self.APP_AUTH_PASSWORD_MEMORY_KIB < 8 * self.APP_AUTH_PASSWORD_PARALLELISM:
            raise ValueError("Argon2 memory must be at least eight times its parallelism")
        return self

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
