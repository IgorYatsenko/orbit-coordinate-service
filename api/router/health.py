from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from api import __version__
from api.dependencies import get_health_manager
from api.managers.health import HealthManager
from models import pydantic

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=pydantic.ServiceInfoResponse, summary="Check HTTP process liveness")
async def liveness() -> pydantic.ServiceInfoResponse:
    return pydantic.ServiceInfoResponse(version=__version__)


@router.get(
    "/health/ready",
    response_model=pydantic.ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": pydantic.ReadinessResponse}},
    summary="Check PostgreSQL, Redis and calculation pool availability",
)
async def readiness(
    response: Response,
    manager: Annotated[HealthManager, Depends(get_health_manager)],
) -> pydantic.ReadinessResponse:
    result = await manager.readiness()
    if result.status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
