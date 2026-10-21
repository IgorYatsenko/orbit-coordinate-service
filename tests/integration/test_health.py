import httpx
import pytest

from api import __version__
from api.main import Application

pytestmark = pytest.mark.integration


async def test_ready_after_real_lifespan_and_migrations(client: httpx.AsyncClient) -> None:
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.content == b""
    assert "content-type" not in ready.headers
    live = await client.get("/health/live")
    assert live.status_code == 200


async def test_stopped_registered_auth_service_makes_readiness_unavailable(
    application: Application, client: httpx.AsyncClient
) -> None:
    await application.services.auth.stop()
    ready = await client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.content == b""
    assert (await client.get("/health/live")).status_code == 200


async def test_openapi_exposes_service_version_and_readiness_failure(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["version"] == __version__
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
    for code in ("200", "503"):
        assert "content" not in schema["paths"]["/health/ready"]["get"]["responses"][code]
