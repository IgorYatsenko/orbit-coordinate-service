from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from api.dependencies import get_satellite_manager
from api.managers.satellites import SatelliteManager
from models.pydantic.errors import ErrorResponse
from models.pydantic.satellites import SatellitePage, SatelliteResponse, SatelliteWrite

router = APIRouter(
    prefix="/api/v1/satellites",
    tags=["Satellites"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)

Manager = Annotated[SatelliteManager, Depends(get_satellite_manager)]


@router.post("", response_model=SatelliteResponse, status_code=201, summary="Register satellite metadata")
async def create(data: SatelliteWrite, manager: Manager) -> SatelliteResponse:
    return await manager.create(data)


@router.get("", response_model=SatellitePage, summary="List satellites in NORAD ID order")
async def list_page(
    manager: Manager,
    after_norad_id: Annotated[int, Query(ge=0, le=999999999)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SatellitePage:
    return await manager.list_page(after_norad_id=after_norad_id, limit=limit)


@router.get("/{satellite_id}", response_model=SatelliteResponse, summary="Get satellite metadata")
async def get(satellite_id: UUID, manager: Manager) -> SatelliteResponse:
    return await manager.get(satellite_id)


@router.put("/{satellite_id}", response_model=SatelliteResponse, summary="Replace all satellite metadata")
async def replace(satellite_id: UUID, data: SatelliteWrite, manager: Manager) -> SatelliteResponse:
    return await manager.replace(satellite_id, data)


@router.delete("/{satellite_id}", status_code=204, response_class=Response, summary="Delete satellite metadata")
async def remove(satellite_id: UUID, manager: Manager) -> Response:
    await manager.remove(satellite_id)
    return Response(status_code=204)
