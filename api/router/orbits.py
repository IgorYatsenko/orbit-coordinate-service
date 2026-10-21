from typing import Annotated

from fastapi import APIRouter, Body, Depends, Response, status

from api.dependencies import get_orbit_manager
from api.managers.orbits import OrbitManager
from api.router.examples import COORDINATE_EXAMPLES
from models import pydantic
from models.pydantic.errors import ErrorResponse

router = APIRouter(prefix="/api/v1/orbits", tags=["Orbits"])


@router.post(
    "/coordinates",
    response_model=pydantic.CoordinateResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": pydantic.CalculationErrorResponse | pydantic.RequestValidationErrorResponse
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": pydantic.CalculationErrorResponse | ErrorResponse},
    },
    summary="Calculate a WGS84 trajectory from TLE or CelesTrak GP JSON",
)
async def coordinates(
    request: Annotated[pydantic.CoordinateRequest, Body(openapi_examples=COORDINATE_EXAMPLES)],
    manager: Annotated[OrbitManager, Depends(get_orbit_manager)],
) -> Response:
    result = await manager.calculate(request)
    # The worker validates and serializes the declared response model outside the HTTP event loop.
    return Response(
        content=result.payload,
        media_type="application/json",
        headers={"Server-Timing": f"compute;dur={result.duration_sec * 1000:.3f}"},
    )
