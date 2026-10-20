import asyncio

from api import __version__
from api.services.compute import Compute
from api.services.postgresql import PostgreSQL
from api.services.redis import Redis
from models import pydantic


class HealthManager:
    def __init__(self, *, database: PostgreSQL, compute: Compute, redis: Redis) -> None:
        self._database = database
        self._compute = compute
        self._redis = redis

    async def readiness(self) -> pydantic.ReadinessResponse:
        database, compute, redis = await asyncio.gather(self._database.ping(), self._compute.ping(), self._redis.ping())
        return pydantic.ReadinessResponse(
            status="ok" if database and compute and redis else "unavailable",
            version=__version__,
            database="ok" if database else "unavailable",
            compute="ok" if compute else "unavailable",
            redis="ok" if redis else "unavailable",
        )
