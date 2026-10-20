from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.pydantic.satellites import SatelliteWrite
from models.sqlalchemy import Satellite


async def create(session: AsyncSession, data: SatelliteWrite) -> Satellite:
    result = await session.scalars(insert(Satellite).values(**data.model_dump()).returning(Satellite))
    return result.one()


async def get(session: AsyncSession, satellite_id: UUID) -> Satellite | None:
    return await session.scalar(select(Satellite).where(Satellite.id == satellite_id))


async def list_page(session: AsyncSession, *, after_norad_id: int, limit: int) -> list[Satellite]:
    result = await session.scalars(
        select(Satellite).where(Satellite.norad_id > after_norad_id).order_by(Satellite.norad_id).limit(limit)
    )
    return list(result)


async def replace(session: AsyncSession, satellite_id: UUID, data: SatelliteWrite) -> Satellite | None:
    return await session.scalar(
        update(Satellite)
        .where(Satellite.id == satellite_id)
        .values(**data.model_dump(), updated_at=func.now())
        .returning(Satellite)
    )


async def remove(session: AsyncSession, satellite_id: UUID) -> UUID | None:
    return await session.scalar(delete(Satellite).where(Satellite.id == satellite_id).returning(Satellite.id))
