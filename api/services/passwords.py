import asyncio
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from api.services.base import BaseService
from api.settings import _Settings
from models.exceptions.access import AuthenticationBusy


class Passwords(BaseService):
    def __init__(self, *, config: _Settings) -> None:
        self._hasher = PasswordHasher(
            memory_cost=config.APP_AUTH_PASSWORD_MEMORY_KIB,
            time_cost=config.APP_AUTH_PASSWORD_TIME_COST,
            parallelism=config.APP_AUTH_PASSWORD_PARALLELISM,
        )
        self._workers = config.APP_AUTH_PASSWORD_WORKERS
        self._pending: set[asyncio.Task[bool]] = set()
        self._dummy_hash: str | None = None

    async def start(self) -> None:
        self._dummy_hash = await self.hash(secrets.token_urlsafe(32))

    async def stop(self) -> None:
        self._dummy_hash = None
        if self._pending:
            await asyncio.gather(*self._pending)

    async def ping(self) -> bool:
        return self._dummy_hash is not None

    async def hash(self, password: str) -> str:
        # Used by the demonstration task and once during startup, not by a public registration route.
        return await asyncio.to_thread(self._hasher.hash, password)

    def _verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False

    async def verify(self, encoded: str | None, password: str) -> bool:
        if self._dummy_hash is None:
            raise RuntimeError("Password service has not been started")
        if len(self._pending) >= self._workers:
            raise AuthenticationBusy()
        task = asyncio.create_task(asyncio.to_thread(self._verify, encoded or self._dummy_hash, password))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        # Cancellation must not release a slot while Argon2 still occupies memory in its thread.
        return await asyncio.shield(task)
