import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import jwt
import pytest

from api.main import Application
from api.services.passwords import Passwords
from api.settings import _Settings
from api.tokens import Tokens
from models.exceptions.access import AuthenticationBusy, AuthenticationFailed
from models.pydantic.auth import AuthenticatedUser, TokenClaims


@pytest.fixture
def user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), username="reviewer", is_active=True, created_at=datetime.now(UTC), token_version=0
    )


def test_signed_token_roundtrip_has_bounded_lifetime(user: AuthenticatedUser) -> None:
    settings = _Settings(APP_AUTH_TOKEN_TTL_SEC=37)
    tokens = Tokens(config=settings)
    issued = tokens.issue(user)
    claims = tokens.decode(issued.access_token)
    assert claims.sub == user.id
    assert claims.ver == user.token_version
    assert claims.exp - claims.iat == issued.expires_in == 37
    assert issued.access_token not in repr(issued)


@pytest.mark.parametrize(
    "mutation",
    ["expired", "signature", "audience", "issuer", "missing_exp", "invalid_sub", "boolean_version", "algorithm"],
)
def test_invalid_tokens_are_rejected(user: AuthenticatedUser, mutation: str) -> None:
    settings = _Settings()
    now = int(datetime.now(UTC).timestamp())
    claims = TokenClaims(
        sub=user.id,
        ver=0,
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
    elif mutation == "boolean_version":
        claims["ver"] = True
    elif mutation == "algorithm":
        algorithm = "HS384"
        key = "test-key-for-unsupported-algorithm" * 2
    token = jwt.encode(claims, key, algorithm=algorithm)
    with pytest.raises(AuthenticationFailed):
        Tokens(config=settings).decode(token)


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


async def test_cancelled_password_check_keeps_its_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    passwords = Passwords(
        config=_Settings(
            APP_AUTH_PASSWORD_WORKERS=1,
            APP_AUTH_PASSWORD_MEMORY_KIB=1024,
            APP_AUTH_PASSWORD_TIME_COST=1,
            APP_AUTH_PASSWORD_PARALLELISM=1,
        )
    )
    await passwords.start()
    pending = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()

    async def delayed_verification(*_args: object) -> bool:
        entered.set()
        return await pending

    monkeypatch.setattr("api.services.passwords.asyncio.to_thread", delayed_verification)
    checking = asyncio.create_task(passwords.verify(None, "unknown-password"))
    await entered.wait()
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking
    with pytest.raises(AuthenticationBusy):
        await passwords.verify(None, "another-password")
    pending.set_result(False)
    await passwords.stop()
