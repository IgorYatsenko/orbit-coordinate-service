from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from api.router.auth import router as auth_router
from api.router.health import router as health_router
from api.router.metrics import router as metrics_router
from api.router.orbits import router as orbits_router
from api.router.satellites import router as satellites_router
from models.pydantic.errors import ErrorResponse, RequestValidationErrorResponse

router = APIRouter()
router.include_router(health_router)
router.include_router(metrics_router)
router.include_router(auth_router)
protected = APIRouter(
    dependencies=[Depends(get_current_user)],
    responses={
        401: {"model": ErrorResponse},
        422: {"model": RequestValidationErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
protected.include_router(orbits_router)
protected.include_router(satellites_router)
router.include_router(protected)

__all__ = ["router"]
