from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status

from api.dependencies import get_orbit_manager
from api.managers.orbits import OrbitManager
from api.router.examples import COORDINATE_EXAMPLES
from models import pydantic
from models.exceptions import ComputeBusy, ComputeTimeout, ComputeUnavailable, OrbitCalculationError
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
    if request.point_count > manager.max_points:
        detail = pydantic.CalculationErrorDetail(
            code="point_limit_exceeded",
            message=f"Requested {request.point_count} points; limit is {manager.max_points}",
        )
        raise HTTPException(status_code=422, detail=detail.model_dump(mode="json"))
    try:
        result = await manager.calculate(request)
    except OrbitCalculationError as error:
        detail = pydantic.CalculationErrorDetail(
            code="propagation_failed" if error.time is not None else "invalid_orbit",
            message=str(error),
            time=error.time,
        )
        raise HTTPException(status_code=422, detail=detail.model_dump(mode="json")) from error
    except (ComputeBusy, ComputeUnavailable, ComputeTimeout) as error:
        code = "compute_busy" if isinstance(error, ComputeBusy) else "compute_unavailable"
        if isinstance(error, ComputeTimeout):
            code = "compute_timeout"
        detail = pydantic.CalculationErrorDetail(code=code, message=str(error))
        raise HTTPException(status_code=503, detail=detail.model_dump(mode="json")) from error
    # The worker validates and serializes the declared response model outside the HTTP event loop.
    return Response(
        content=result.payload,
        media_type="application/json",
        headers={"Server-Timing": f"compute;dur={result.duration_sec * 1000:.3f}"},
    )
