from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    code: str
    message: str

    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorResponse(BaseModel):
    detail: ErrorDetail

    model_config = ConfigDict(extra="forbid", frozen=True)


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str

    model_config = ConfigDict(extra="forbid", frozen=True)


class RequestValidationErrorResponse(BaseModel):
    detail: list[ValidationIssue]

    model_config = ConfigDict(extra="forbid", frozen=True)
