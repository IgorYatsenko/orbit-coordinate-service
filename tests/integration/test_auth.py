import asyncio

import httpx
import pytest
from sqlalchemy import select, update

from api.main import Application
from api.services import Services
from api.settings import _Settings
from dev.project_user import create_user_setup
from models.exceptions.access import DatabaseUnavailable
from models.pydantic.auth import LoginRequest
from models.sqlalchemy import User

pytestmark = pytest.mark.integration


async def test_login_and_current_user_do_not_expose_secrets(
    application: Application,
    anonymous_client: httpx.AsyncClient,
    registered_user: None,
    user_credentials: LoginRequest,
) -> None:
    response = await anonymous_client.post(
        "/api/v1/auth/login", json={"username": " REVIEWER ", "password": user_credentials.password.get_secret_value()}
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == application.services.config.APP_AUTH_TOKEN_TTL_SEC
    me = await anonymous_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"})
    assert me.status_code == 200
    assert set(me.json()) == {"id", "username", "is_active", "created_at"}
    async with application.services.database.session() as session:
        encoded = await session.scalar(select(User.password_hash).where(User.username == "reviewer"))
    assert encoded is not None and encoded.startswith("$argon2id$")
    assert user_credentials.password.get_secret_value() not in encoded


async def test_unknown_user_and_wrong_password_have_identical_responses(
    anonymous_client: httpx.AsyncClient, registered_user: None
) -> None:
    unknown = await anonymous_client.post("/api/v1/auth/login", json={"username": "unknown", "password": "wrong"})
    incorrect = await anonymous_client.post("/api/v1/auth/login", json={"username": "reviewer", "password": "wrong"})
    assert unknown.status_code == incorrect.status_code == 401
    assert unknown.json() == incorrect.json()
    secret = "hidden-password-" * 20
    invalid = await anonymous_client.post("/api/v1/auth/login", json={"username": "reviewer", "password": secret})
    assert invalid.status_code == 422
    assert secret not in invalid.text
    assert "input" not in invalid.json()["detail"][0]


async def test_database_access_changes_revoke_existing_tokens(
    application: Application, client: httpx.AsyncClient, user_credentials: LoginRequest
) -> None:
    new_credentials = LoginRequest(username="reviewer", password="a-new-test-password")
    encoded = await application.services.passwords.hash(new_credentials.password.get_secret_value())
    async with application.services.database.session() as session:
        await session.execute(
            update(User)
            .where(User.username == "reviewer")
            .values(password_hash=encoded, token_version=User.token_version + 1)
        )
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"username": "reviewer", "password": user_credentials.password.get_secret_value()}
    )
    assert login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"username": "reviewer", "password": new_credentials.password.get_secret_value()}
    )
    assert new_login.status_code == 200
    client.headers["Authorization"] = f"Bearer {new_login.json()['access_token']}"
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    async with application.services.database.session() as session:
        await session.execute(update(User).where(User.username == "reviewer").values(is_active=False))
    assert await create_user_setup(services=application.services, credentials=new_credentials) is False
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"username": "reviewer", "password": new_credentials.password.get_secret_value()}
        )
    ).status_code == 401


async def test_demo_setup_preserves_existing_user_and_password(
    application: Application, client: httpx.AsyncClient, user_credentials: LoginRequest
) -> None:
    original = (await client.get("/api/v1/auth/me")).json()
    changed = LoginRequest(username=user_credentials.username, password="not-the-original-password")
    assert await create_user_setup(services=application.services, credentials=changed) is False
    assert (await client.get("/api/v1/auth/me")).json() == original
    for credentials, expected in ((user_credentials, 200), (changed, 401)):
        result = await client.post(
            "/api/v1/auth/login",
            json={"username": credentials.username, "password": credentials.password.get_secret_value()},
        )
        assert result.status_code == expected


async def test_concurrent_demo_setup_creates_one_user(application: Application, user_credentials: LoginRequest) -> None:
    results = await asyncio.gather(
        *(create_user_setup(services=application.services, credentials=user_credentials) for _ in range(2))
    )
    assert sorted(results) == [False, True]
    async with application.services.database.session() as session:
        rows = list(await session.scalars(select(User).where(User.username == user_credentials.username)))
    assert len(rows) == 1


async def test_database_connection_refusal_returns_safe_503(
    application: Application, client: httpx.AsyncClient, app_settings: _Settings
) -> None:
    unavailable = Services(
        config=app_settings.model_copy(
            update={"APP_DB_HOST": "127.0.0.1", "APP_DB_PORT": 1, "APP_DB_CONNECT_TIMEOUT_SEC": 0.05}
        )
    ).database
    original = application.services.database
    try:
        with pytest.raises(DatabaseUnavailable):
            await unavailable.start()
        application.services.database = unavailable
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 503
        assert response.json() == {
            "detail": {"code": "database_unavailable", "message": "Database operation could not be completed"}
        }
        ready = await client.get("/health/ready")
        assert ready.status_code == 503 and ready.json()["database"] == "unavailable"
        assert (await client.get("/health/live")).status_code == 200
    finally:
        application.services.database = original
        await unavailable.stop()
