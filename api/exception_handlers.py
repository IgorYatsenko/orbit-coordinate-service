import logging
from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models.exceptions.access import (
    AccessError,
    AuthenticationBusy,
    AuthenticationFailed,
    DatabaseUnavailable,
    RateLimitExceeded,
    RedisUnavailable,
    SatelliteConflict,
    SatelliteNotFound,
)
from models.pydantic.errors import ErrorDetail, ErrorResponse, RequestValidationErrorResponse, ValidationIssue

logger = logging.getLogger(__name__)

_ERRORS: dict[type[AccessError], tuple[int, str]] = {
    AuthenticationFailed: (401, "unauthorized"),
    AuthenticationBusy: (503, "authentication_busy"),
    RateLimitExceeded: (429, "rate_limit_exceeded"),
    RedisUnavailable: (503, "rate_limiter_unavailable"),
    DatabaseUnavailable: (503, "database_unavailable"),
    SatelliteConflict: (409, "satellite_conflict"),
    SatelliteNotFound: (404, "satellite_not_found"),
}


async def access_error_handler(_request: Request, error: Exception) -> JSONResponse:
    failure = cast(AccessError, error)
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


async def database_error_handler(_request: Request, error: Exception) -> JSONResponse:
    # SQLAlchemy exceptions may include SQL parameters. Do not log their text or return them to clients.
    logger.warning("PostgreSQL operation failed: %s", type(error).__name__)
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(
            detail=ErrorDetail(code="database_unavailable", message="Database operation could not be completed")
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
