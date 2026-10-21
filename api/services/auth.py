import asyncio
import secrets
from datetime import UTC, datetime
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import ValidationError

from api.services.base import BaseService
from api.settings import _Settings
from models.exceptions.auth import AuthenticationBusy, AuthenticationFailed
from models.pydantic.auth import TokenClaims, TokenResponse


class Auth(BaseService):
    def __init__(self, *, config: _Settings) -> None:
        self._hasher = PasswordHasher(
            memory_cost=config.APP_AUTH_PASSWORD_MEMORY_KIB,
            time_cost=config.APP_AUTH_PASSWORD_TIME_COST,
            parallelism=config.APP_AUTH_PASSWORD_PARALLELISM,
        )
        self._workers = config.APP_AUTH_PASSWORD_WORKERS
        self._pending: set[asyncio.Task[bool]] = set()
        self._dummy_hash: str | None = None
        self._secret = config.APP_AUTH_TOKEN_SECRET.get_secret_value()
        self._ttl_sec = config.APP_AUTH_TOKEN_TTL_SEC
        self._issuer = config.APP_AUTH_TOKEN_ISSUER
        self._audience = config.APP_AUTH_TOKEN_AUDIENCE

    async def start(self) -> None:
        self._dummy_hash = await self.hash_password(secrets.token_urlsafe(32))

    async def stop(self) -> None:
        self._dummy_hash = None
        if self._pending:
            await asyncio.gather(*self._pending)

    async def ping(self) -> bool:
        return self._dummy_hash is not None

    async def hash_password(self, password: str) -> str:
        # Used by the demonstration task and once during startup, not by a public registration route.
        return await asyncio.to_thread(self._hasher.hash, password)

    def _verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False

    async def verify_password(self, encoded: str | None, password: str) -> bool:
        if self._dummy_hash is None:
            raise RuntimeError("Auth service has not been started")
        if len(self._pending) >= self._workers:
            raise AuthenticationBusy()
        task = asyncio.create_task(asyncio.to_thread(self._verify, encoded or self._dummy_hash, password))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        # Cancellation must not release a slot while Argon2 still occupies memory in its thread.
        return await asyncio.shield(task)

    def issue_token(self, user_id: UUID) -> TokenResponse:
        now = int(datetime.now(UTC).timestamp())
        claims = TokenClaims(sub=user_id, iat=now, exp=now + self._ttl_sec, iss=self._issuer, aud=self._audience)
        return TokenResponse(
            access_token=jwt.encode(claims.model_dump(mode="json"), self._secret, algorithm="HS256"),
            expires_in=self._ttl_sec,
        )

    def decode_token(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "iat", "exp", "iss", "aud"]},
            )
            return TokenClaims.model_validate(payload)
        except (jwt.InvalidTokenError, ValidationError) as exc:
            raise AuthenticationFailed() from exc
