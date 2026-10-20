from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, StringConstraints


def normalize_username(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


Username = Annotated[
    str,
    StringConstraints(strict=True, min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]{2,63}$"),
    BeforeValidator(normalize_username),
]


class LoginRequest(BaseModel):
    username: Username = Field(examples=["testuser"])
    password: SecretStr = Field(min_length=1, max_length=128, examples=["test-password"])

    model_config = ConfigDict(extra="forbid", frozen=True)


class UserResponse(BaseModel):
    id: UUID
    username: Username
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenClaims(BaseModel):
    sub: UUID
    iat: int = Field(ge=0, strict=True)
    exp: int = Field(ge=0, strict=True)
    iss: str
    aud: str

    model_config = ConfigDict(extra="forbid", frozen=True)
