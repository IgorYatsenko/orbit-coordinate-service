import asyncio
import hashlib
import logging
import math
from typing import cast

from redis.asyncio import Redis as RedisClient
from redis.exceptions import RedisError

from api.services.base import BaseService
from api.settings import _Settings
from models.exceptions.auth import RateLimitExceeded
from models.exceptions.infrastructure import RedisUnavailable

logger = logging.getLogger(__name__)

_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('PTTL', KEYS[1])}
"""


class Redis(BaseService):
    def __init__(self, *, config: _Settings) -> None:
        self._config = config
        self._client: RedisClient | None = None

    async def start(self) -> None:
        self._client = RedisClient(
            host=self._config.APP_REDIS_HOST,
            port=self._config.APP_REDIS_PORT,
            db=self._config.APP_REDIS_DB,
            password=self._config.APP_REDIS_PASSWORD.get_secret_value() or None,
            max_connections=self._config.APP_REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=self._config.APP_REDIS_CONNECT_TIMEOUT_SEC,
            socket_timeout=self._config.APP_REDIS_SOCKET_TIMEOUT_SEC,
            decode_responses=True,
        )
        if not await self.ping():
            raise RedisUnavailable()
        logger.info("Redis connection established")

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection pool disposed")

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            async with asyncio.timeout(self._config.APP_REDIS_HEALTHCHECK_TIMEOUT_SEC):
                return bool(await self._client.ping())
        except (RedisError, OSError, TimeoutError) as exc:
            logger.warning("Redis healthcheck failed: %s", type(exc).__name__)
            return False

    async def enforce(self, *, bucket: str, identity: str, limit: int, window_sec: int) -> None:
        if self._client is None:
            raise RedisUnavailable()
        # Fixed-length keys do not expose client addresses and cannot alter the namespace.
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key = f"{self._config.APP_REDIS_KEY_PREFIX}:{bucket}:{digest}"
        try:
            async with asyncio.timeout(self._config.APP_REDIS_SOCKET_TIMEOUT_SEC):
                result = cast(list[int], await self._client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_sec * 1000))
        except (RedisError, OSError, TimeoutError) as exc:
            logger.warning("Redis rate limit failed: %s", type(exc).__name__)
            raise RedisUnavailable() from exc
        count, ttl_ms = result
        if count > limit:
            raise RateLimitExceeded(retry_after_sec=max(1, math.ceil(ttl_ms / 1000)))
