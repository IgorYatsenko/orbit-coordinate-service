import asyncio
from time import monotonic
from unittest.mock import AsyncMock

import pytest

from api.services.redis import Redis
from api.settings import _Settings
from models.exceptions.infrastructure import RedisUnavailable


async def test_limiter_deadline_covers_the_whole_redis_command(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = Redis(config=_Settings(APP_REDIS_SOCKET_TIMEOUT_SEC=0.02))

    async def stalled_command(*_args: object) -> list[int]:
        await asyncio.Event().wait()
        return [1, 1000]

    client = AsyncMock()
    client.eval.side_effect = stalled_command
    monkeypatch.setattr(redis, "_client", client)
    started = monotonic()
    with pytest.raises(RedisUnavailable):
        await redis.enforce(bucket="user", identity="test-id", limit=1, window_sec=1)
    assert monotonic() - started < 1
