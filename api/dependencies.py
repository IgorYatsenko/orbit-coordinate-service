from typing import cast

from fastapi import Request

from api.managers.health import HealthManager
from api.managers.orbits import OrbitManager
from api.services import Services


def get_health_manager(request: Request) -> HealthManager:
    services = cast(Services, request.app.state.services)
    return HealthManager(database=services.database, compute=services.compute)


def get_orbit_manager(request: Request) -> OrbitManager:
    services = cast(Services, request.app.state.services)
    return OrbitManager(compute=services.compute, max_points=services.config.APP_COMPUTE_MAX_POINTS)
