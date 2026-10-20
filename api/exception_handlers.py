from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models.pydantic.orbits import RequestValidationErrorResponse, ValidationIssue


async def request_validation_error_handler(_request: Request, error: Exception) -> JSONResponse:
    failure = cast(RequestValidationError, error)
    response = RequestValidationErrorResponse(
        detail=[
            ValidationIssue(loc=list(issue["loc"]), msg=issue["msg"], type=issue["type"]) for issue in failure.errors()
        ]
    )
    # Echoing rejected inputs can reintroduce NaN/Infinity into the JSON error response.
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))
