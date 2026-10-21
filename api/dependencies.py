from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.managers.auth import AuthManager
from api.managers.orbits import OrbitManager
from api.managers.satellites import SatelliteManager
from api.services import Services
from models.exceptions.auth import AuthenticationFailed
from models.pydantic.auth import UserResponse

bearer = HTTPBearer(auto_error=False, description="Obtain a token with POST /api/v1/auth/login, then paste it here.")


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def get_orbit_manager(request: Request) -> OrbitManager:
    services = get_services(request)
    return OrbitManager(compute=services.compute, max_points=services.config.APP_COMPUTE_MAX_POINTS)


def get_auth_manager(request: Request) -> AuthManager:
    services = get_services(request)
    return AuthManager(
        database=services.database,
        auth=services.auth,
        redis=services.redis,
        config=services.config,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    manager: Annotated[AuthManager, Depends(get_auth_manager)],
) -> UserResponse:
    if credentials is None:
        raise AuthenticationFailed()
    return await manager.authenticate(credentials.credentials)


async def limit_login(request: Request, manager: Annotated[AuthManager, Depends(get_auth_manager)]) -> None:
    await manager.limit_login(request.client.host if request.client is not None else "unknown")


def get_satellite_manager(request: Request) -> SatelliteManager:
    services = get_services(request)
    return SatelliteManager(database=services.database)
