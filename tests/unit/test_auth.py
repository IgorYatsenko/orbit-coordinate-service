import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import jwt
import pytest

from api.dependencies import get_auth_manager, limit_login
from api.main import Application
from api.managers.auth import AuthManager
from api.services.auth import Auth
from api.settings import _Settings
from models.exceptions.auth import AuthenticationBusy, AuthenticationFailed
from models.pydantic.auth import TokenClaims


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


def test_signed_token_roundtrip_has_bounded_lifetime(user_id: UUID) -> None:
    settings = _Settings(APP_AUTH_TOKEN_TTL_SEC=37)
    auth = Auth(config=settings)
    issued = auth.issue_token(user_id)
    claims = auth.decode_token(issued.access_token)
    assert claims.sub == user_id
    assert claims.exp - claims.iat == issued.expires_in == 37
    assert issued.access_token not in repr(issued)


@pytest.mark.parametrize(
    "mutation",
    ["expired", "signature", "audience", "issuer", "missing_exp", "invalid_sub", "boolean_iat", "algorithm"],
)
def test_invalid_tokens_are_rejected(user_id: UUID, mutation: str) -> None:
    settings = _Settings()
    now = int(datetime.now(UTC).timestamp())
    claims = TokenClaims(
        sub=user_id,
        iat=now,
        exp=now + 60,
        iss=settings.APP_AUTH_TOKEN_ISSUER,
        aud=settings.APP_AUTH_TOKEN_AUDIENCE,
    ).model_dump(mode="json")
    key = settings.APP_AUTH_TOKEN_SECRET.get_secret_value()
    algorithm = "HS256"
    if mutation == "expired":
        claims.update(iat=now - 60, exp=now - 1)
    elif mutation == "signature":
        key = "a-different-test-signing-secret-of-32-characters"
    elif mutation == "audience":
        claims["aud"] = "another-api"
    elif mutation == "issuer":
        claims["iss"] = "another-issuer"
    elif mutation == "missing_exp":
        del claims["exp"]
    elif mutation == "invalid_sub":
        claims["sub"] = "not-a-uuid"
    elif mutation == "boolean_iat":
        claims["iat"] = True
    elif mutation == "algorithm":
        algorithm = "HS384"
        key = "test-key-for-unsupported-algorithm" * 2
    token = jwt.encode(claims, key, algorithm=algorithm)
    with pytest.raises(AuthenticationFailed):
        Auth(config=settings).decode_token(token)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/orbits/coordinates"),
        ("GET", "/api/v1/satellites"),
        ("POST", "/api/v1/satellites"),
        ("PUT", f"/api/v1/satellites/{uuid4()}"),
        ("DELETE", f"/api/v1/satellites/{uuid4()}"),
    ],
)
async def test_business_routes_require_a_bearer_token(method: str, path: str) -> None:
    app = Application(settings=_Settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"]["code"] == "unauthorized"


@pytest.mark.parametrize("password", ["\ud800", "\udfff", "secret\ud800value"])
async def test_login_rejects_invalid_unicode_before_password_verification(password: str) -> None:
    app = Application(settings=_Settings())
    manager = AsyncMock(spec=AuthManager)
    app.dependency_overrides[get_auth_manager] = lambda: manager
    app.dependency_overrides[limit_login] = lambda: None
    payload = json.dumps({"username": "testuser", "password": password}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login", content=payload, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {"loc": ["body", "password"], "msg": "Value error, Password must be valid UTF-8", "type": "value_error"}
        ]
    }
    manager.login.assert_not_awaited()


async def test_login_preserves_valid_unicode_and_password_whitespace() -> None:
    app = Application(settings=_Settings())
    manager = AsyncMock(spec=AuthManager)
    manager.login.side_effect = AuthenticationFailed()
    app.dependency_overrides[get_auth_manager] = lambda: manager
    app.dependency_overrides[limit_login] = lambda: None
    password = " пароль 🚀 "
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": "testuser", "password": password})
    assert response.status_code == 401
    credentials = manager.login.await_args.args[0]
    assert credentials.password.get_secret_value() == password


async def test_cancelled_password_check_keeps_its_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = Auth(
        config=_Settings(
            APP_AUTH_PASSWORD_WORKERS=1,
            APP_AUTH_PASSWORD_MEMORY_KIB=1024,
            APP_AUTH_PASSWORD_TIME_COST=1,
            APP_AUTH_PASSWORD_PARALLELISM=1,
        )
    )
    await auth.start()
    pending = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()

    async def delayed_verification(*_args: object) -> bool:
        entered.set()
        return await pending

    monkeypatch.setattr("api.services.auth.asyncio.to_thread", delayed_verification)
    checking = asyncio.create_task(auth.verify_password(None, "unknown-password"))
    await entered.wait()
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking
    with pytest.raises(AuthenticationBusy):
        await auth.verify_password(None, "another-password")
    pending.set_result(False)
    await auth.stop()
