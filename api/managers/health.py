from api import __version__
from api.services.postgresql import PostgreSQL
from models import pydantic


class HealthManager:
    def __init__(self, *, database: PostgreSQL) -> None:
        self._database = database

    async def readiness(self) -> pydantic.ReadinessResponse:
        available = await self._database.ping()
        return pydantic.ReadinessResponse(
            status="ok" if available else "unavailable",
            version=__version__,
            database="ok" if available else "unavailable",
        )
