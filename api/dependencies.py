from typing import cast

from fastapi import Request

from api.managers.health import HealthManager
from api.services import Services


def get_health_manager(request: Request) -> HealthManager:
    services = cast(Services, request.app.state.services)
    return HealthManager(database=services.database)
