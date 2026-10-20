import httpx
import pytest

from api import __version__

pytestmark = pytest.mark.integration


async def test_ready_after_real_lifespan_and_migrations(client: httpx.AsyncClient) -> None:
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "version": __version__, "database": "ok", "compute": "ok"}
    live = await client.get("/health/live")
    assert live.status_code == 200


async def test_openapi_exposes_service_version_and_readiness_failure(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["version"] == __version__
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
