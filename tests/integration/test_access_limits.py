import asyncio

import httpx
import pytest

from api.db import users
from api.main import Application
from api.services.redis import Redis
from api.settings import _Settings
from models.exceptions.access import RateLimitExceeded, RedisUnavailable
from models.pydantic.auth import LoginRequest

pytestmark = pytest.mark.integration


@pytest.fixture
def app_settings(app_settings: _Settings) -> _Settings:
    return app_settings.model_copy(
        update={
            "APP_RATE_LIMIT_USER_REQUESTS": 2,
            "APP_RATE_LIMIT_USER_WINDOW_SEC": 1,
            "APP_RATE_LIMIT_LOGIN_REQUESTS": 3,
            "APP_RATE_LIMIT_LOGIN_WINDOW_SEC": 60,
        }
    )


async def test_user_limit_is_shared_by_tokens_but_isolated_between_users(
    application: Application, client: httpx.AsyncClient, user_credentials: LoginRequest
) -> None:
    login = await client.post(
        "/api/v1/auth/login", json={"username": "reviewer", "password": user_credentials.password.get_secret_value()}
    )
    same_user_token = login.json()["access_token"]
    assert (await client.get("/api/v1/satellites")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    rejected = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {same_user_token}"})
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["code"] == "rate_limit_exceeded"
    assert int(rejected.headers["retry-after"]) == 1
    other = LoginRequest(username="other-user", password="another-test-password")
    encoded = await application.services.auth.hash_password(other.password.get_secret_value())
    async with application.services.database.session() as session:
        await users.create_if_missing(session, username=other.username, password_hash=encoded)
    second = await client.post(
        "/api/v1/auth/login", json={"username": other.username, "password": other.password.get_secret_value()}
    )
    assert second.status_code == 200
    assert (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"})
    ).status_code == 200
    await asyncio.sleep(1.05)
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_login_rate_counts_failures_and_ignores_untrusted_forwarding_headers(
    anonymous_client: httpx.AsyncClient,
) -> None:
    for index in range(3):
        response = await anonymous_client.post(
            "/api/v1/auth/login",
            json={"username": "unknown", "password": "wrong"},
            headers={"X-Forwarded-For": f"192.0.2.{index}"},
        )
        assert response.status_code == 401
    rejected = await anonymous_client.post("/api/v1/auth/login", json={"username": "unknown", "password": "wrong"})
    assert rejected.status_code == 429
    assert 1 <= int(rejected.headers["retry-after"]) <= 60
    assert (await anonymous_client.get("/health/live")).status_code == 200


async def test_two_redis_clients_enforce_one_atomic_limit(application: Application, app_settings: _Settings) -> None:
    second = Redis(config=app_settings)
    await second.start()

    async def attempt(service: Redis) -> bool:
        try:
            await service.enforce(bucket="atomic", identity="one-client", limit=5, window_sec=10)
            return True
        except RateLimitExceeded as exc:
            assert 1 <= exc.retry_after_sec <= 10
            return False

    try:
        outcomes = await asyncio.gather(
            *(attempt(service) for service in (application.services.redis, second) for _ in range(10))
        )
        assert sum(outcomes) == 5
    finally:
        await second.stop()


async def test_redis_unavailability_closes_protected_operations(
    application: Application, client: httpx.AsyncClient
) -> None:
    await application.services.redis.stop()
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limiter_unavailable"
    ready = await client.get("/health/ready")
    assert ready.status_code == 503 and ready.content == b""
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})).status_code == 401


async def test_redis_connection_failure_does_not_open_access(app_settings: _Settings) -> None:
    redis = Redis(
        config=app_settings.model_copy(
            update={
                "APP_REDIS_PORT": 1,
                "APP_REDIS_CONNECT_TIMEOUT_SEC": 0.05,
                "APP_REDIS_HEALTHCHECK_TIMEOUT_SEC": 0.1,
            }
        )
    )
    try:
        with pytest.raises(RedisUnavailable):
            await redis.start()
        with pytest.raises(RedisUnavailable):
            await redis.enforce(bucket="login", identity="client", limit=1, window_sec=1)
        assert await redis.ping() is False
    finally:
        await redis.stop()
