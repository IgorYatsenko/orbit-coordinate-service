import logging
import traceback
from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models.exceptions.auth import AuthenticationBusy, AuthenticationFailed, RateLimitExceeded
from models.exceptions.base import ApplicationError
from models.exceptions.infrastructure import DatabaseUnavailable, RedisUnavailable
from models.exceptions.orbits import (
    CalculationError,
    ComputeBusy,
    ComputeTimeout,
    ComputeUnavailable,
    OrbitCalculationError,
    PointLimitExceeded,
)
from models.exceptions.satellites import SatelliteConflict, SatelliteNotFound
from models.pydantic.errors import ErrorDetail, ErrorResponse, RequestValidationErrorResponse, ValidationIssue
from models.pydantic.orbits import CalculationErrorCode, CalculationErrorDetail, CalculationErrorResponse

logger = logging.getLogger(__name__)

_ERRORS: dict[type[ApplicationError], tuple[int, str]] = {
    AuthenticationFailed: (401, "unauthorized"),
    AuthenticationBusy: (503, "authentication_busy"),
    RateLimitExceeded: (429, "rate_limit_exceeded"),
    RedisUnavailable: (503, "rate_limiter_unavailable"),
    DatabaseUnavailable: (503, "database_unavailable"),
    SatelliteConflict: (409, "satellite_conflict"),
    SatelliteNotFound: (404, "satellite_not_found"),
}

_CALCULATION_ERRORS: dict[type[CalculationError], tuple[int, CalculationErrorCode]] = {
    PointLimitExceeded: (422, "point_limit_exceeded"),
    ComputeBusy: (503, "compute_busy"),
    ComputeUnavailable: (503, "compute_unavailable"),
    ComputeTimeout: (503, "compute_timeout"),
}


async def application_error_handler(_request: Request, error: Exception) -> JSONResponse:
    failure = cast(ApplicationError, error)
    status_code, code = _ERRORS[type(failure)]
    headers = {}
    if isinstance(failure, AuthenticationFailed):
        headers["WWW-Authenticate"] = "Bearer"
    if isinstance(failure, RateLimitExceeded):
        headers["Retry-After"] = str(failure.retry_after_sec)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(detail=ErrorDetail(code=code, message=str(failure))).model_dump(mode="json"),
        headers=headers,
    )


async def calculation_error_handler(_request: Request, error: Exception) -> JSONResponse:
    failure = cast(CalculationError, error)
    if isinstance(failure, OrbitCalculationError):
        status_code = 422
        detail = CalculationErrorDetail(
            code="propagation_failed" if failure.time is not None else "invalid_orbit",
            message=str(failure),
            time=failure.time,
        )
    else:
        status_code, code = _CALCULATION_ERRORS[type(failure)]
        detail = CalculationErrorDetail(code=code, message=str(failure))
    return JSONResponse(
        status_code=status_code, content=CalculationErrorResponse(detail=detail).model_dump(mode="json")
    )


async def database_error_handler(_request: Request, error: Exception) -> JSONResponse:
    # Only stack locations are logged: exception text and chained causes can expose SQL parameters.
    stack = "".join(
        f"  {frame.filename}:{frame.lineno} in {frame.name}\n" for frame in traceback.extract_tb(error.__traceback__)
    )
    logger.error("Unexpected PostgreSQL error: %s\n%s", type(error).__name__, stack)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail=ErrorDetail(code="internal_error", message="An internal database error occurred")
        ).model_dump(mode="json"),
    )


async def request_validation_error_handler(_request: Request, error: Exception) -> JSONResponse:
    failure = cast(RequestValidationError, error)
    response = RequestValidationErrorResponse(
        detail=[
            ValidationIssue(loc=list(issue["loc"]), msg=issue["msg"], type=issue["type"]) for issue in failure.errors()
        ]
    )
    # Echoing rejected inputs can reintroduce NaN/Infinity into the JSON error response.
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))
