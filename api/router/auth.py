from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api.dependencies import get_auth_manager, get_current_user, limit_login
from api.managers.auth import AuthManager
from models.pydantic.auth import LoginRequest, TokenResponse, UserResponse
from models.pydantic.errors import ErrorResponse, RequestValidationErrorResponse

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
    responses={
        401: {"model": ErrorResponse},
        422: {"model": RequestValidationErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limit_login)], summary="Sign in")
async def login(
    data: LoginRequest, response: Response, manager: Annotated[AuthManager, Depends(get_auth_manager)]
) -> TokenResponse:
    result = await manager.login(data)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return result


@router.get("/me", response_model=UserResponse, summary="Get current user")
async def current_user(user: Annotated[UserResponse, Depends(get_current_user)]) -> UserResponse:
    return user
