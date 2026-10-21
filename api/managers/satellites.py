from uuid import UUID

from sqlalchemy.exc import IntegrityError

from api.db import satellites
from api.db.errors import is_unique_violation
from api.services.postgresql import PostgreSQL
from models.exceptions.satellites import SatelliteConflict, SatelliteNotFound
from models.pydantic.satellites import SatellitePage, SatelliteResponse, SatelliteWrite


class SatelliteManager:
    def __init__(self, *, database: PostgreSQL) -> None:
        self._database = database

    async def create(self, data: SatelliteWrite) -> SatelliteResponse:
        try:
            async with self._database.session() as session:
                result = SatelliteResponse.model_validate(await satellites.create(session, data))
            return result
        except IntegrityError as exc:
            if is_unique_violation(exc, constraint="uq_satellites_norad_id"):
                raise SatelliteConflict() from exc
            raise

    async def get(self, satellite_id: UUID) -> SatelliteResponse:
        async with self._database.session() as session:
            row = await satellites.get(session, satellite_id)
            if row is None:
                raise SatelliteNotFound()
            return SatelliteResponse.model_validate(row)

    async def list_page(self, *, after_norad_id: int, limit: int) -> SatellitePage:
        async with self._database.session() as session:
            rows = await satellites.list_page(session, after_norad_id=after_norad_id, limit=limit + 1)
            items = [SatelliteResponse.model_validate(row) for row in rows[:limit]]
        return SatellitePage(items=items, next_after_norad_id=items[-1].norad_id if len(rows) > limit else None)

    async def replace(self, satellite_id: UUID, data: SatelliteWrite) -> SatelliteResponse:
        try:
            async with self._database.session() as session:
                row = await satellites.replace(session, satellite_id, data)
                if row is None:
                    raise SatelliteNotFound()
                result = SatelliteResponse.model_validate(row)
            return result
        except IntegrityError as exc:
            if is_unique_violation(exc, constraint="uq_satellites_norad_id"):
                raise SatelliteConflict() from exc
            raise

    async def remove(self, satellite_id: UUID) -> None:
        async with self._database.session() as session:
            if await satellites.remove(session, satellite_id) is None:
                raise SatelliteNotFound()
