from api.db import users
from api.services.passwords import Passwords
from api.services.postgresql import PostgreSQL
from api.services.redis import Redis
from api.settings import _Settings
from api.tokens import Tokens
from models.exceptions.access import AuthenticationFailed
from models.pydantic.auth import AuthenticatedUser, LoginRequest, TokenResponse


class AuthManager:
    def __init__(
        self, *, database: PostgreSQL, passwords: Passwords, redis: Redis, tokens: Tokens, config: _Settings
    ) -> None:
        self._database = database
        self._passwords = passwords
        self._redis = redis
        self._tokens = tokens
        self._config = config

    async def limit_login(self, client_ip: str) -> None:
        await self._redis.enforce(
            bucket="login",
            identity=client_ip,
            limit=self._config.APP_RATE_LIMIT_LOGIN_REQUESTS,
            window_sec=self._config.APP_RATE_LIMIT_LOGIN_WINDOW_SEC,
        )

    async def login(self, credentials: LoginRequest) -> TokenResponse:
        async with self._database.session() as session:
            user = await users.get_by_username(session, credentials.username)
        # Unknown and disabled accounts still perform an Argon2 check, without holding a DB transaction.
        encoded = user.password_hash if user is not None else None
        valid = await self._passwords.verify(encoded, credentials.password.get_secret_value())
        if user is None or not user.is_active or not valid:
            raise AuthenticationFailed()
        return self._tokens.issue(AuthenticatedUser.model_validate(user))

    async def authenticate(self, token: str) -> AuthenticatedUser:
        claims = self._tokens.decode(token)
        await self._redis.enforce(
            bucket="user",
            identity=str(claims.sub),
            limit=self._config.APP_RATE_LIMIT_USER_REQUESTS,
            window_sec=self._config.APP_RATE_LIMIT_USER_WINDOW_SEC,
        )
        async with self._database.session() as session:
            user = await users.get_by_id(session, claims.sub)
        if user is None or not user.is_active or user.token_version != claims.ver:
            raise AuthenticationFailed()
        return AuthenticatedUser.model_validate(user)
