import asyncio

from api import __version__
from api.services.compute import Compute
from api.services.postgresql import PostgreSQL
from models import pydantic


class HealthManager:
    def __init__(self, *, database: PostgreSQL, compute: Compute) -> None:
        self._database = database
        self._compute = compute

    async def readiness(self) -> pydantic.ReadinessResponse:
        database, compute = await asyncio.gather(self._database.ping(), self._compute.ping())
        return pydantic.ReadinessResponse(
            status="ok" if database and compute else "unavailable",
            version=__version__,
            database="ok" if database else "unavailable",
            compute="ok" if compute else "unavailable",
        )
