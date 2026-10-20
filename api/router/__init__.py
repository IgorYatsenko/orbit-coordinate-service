from fastapi import APIRouter

from api.router.health import router as health_router
from api.router.orbits import router as orbits_router

router = APIRouter()
router.include_router(health_router)
router.include_router(orbits_router)

__all__ = ["router"]
