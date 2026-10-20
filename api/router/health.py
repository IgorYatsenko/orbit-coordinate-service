from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from api import __version__
from api.dependencies import get_services
from api.services import Services
from models import pydantic

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=pydantic.ServiceInfoResponse, summary="Check HTTP process liveness")
async def liveness() -> pydantic.ServiceInfoResponse:
    return pydantic.ServiceInfoResponse(version=__version__)


@router.get(
    "/health/ready",
    response_class=Response,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "A registered service is unavailable"}},
    summary="Check all registered services",
)
async def readiness(
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    available = await services.healthcheck()
    return Response(status_code=status.HTTP_200_OK if available else status.HTTP_503_SERVICE_UNAVAILABLE)
