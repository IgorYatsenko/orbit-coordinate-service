from unittest.mock import AsyncMock

import httpx
import pytest

from api import __version__
from api.main import Application
from api.settings import _Settings


async def test_liveness_does_not_contact_database(monkeypatch: pytest.MonkeyPatch) -> None:
    app = Application(settings=_Settings())
    pings = []
    for service in (app.services.database, app.services.redis, app.services.passwords, app.services.compute):
        ping = AsyncMock(side_effect=AssertionError("Liveness must not access services"))
        monkeypatch.setattr(service, "ping", ping)
        pings.append(ping)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
    for ping in pings:
        ping.assert_not_awaited()


@pytest.mark.parametrize("unavailable", [None, "database", "redis", "passwords", "compute"])
async def test_readiness_requires_every_registered_service_and_returns_no_body(
    monkeypatch: pytest.MonkeyPatch, unavailable: str | None
) -> None:
    app = Application(settings=_Settings())
    pings = []
    for name in ("database", "redis", "passwords", "compute"):
        ping = AsyncMock(return_value=name != unavailable)
        monkeypatch.setattr(getattr(app.services, name), "ping", ping)
        pings.append(ping)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == (200 if unavailable is None else 503)
    assert response.content == b""
    assert "content-type" not in response.headers
    for ping in pings:
        ping.assert_awaited_once_with()


async def test_readiness_returns_empty_503_when_a_service_probe_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = Application(settings=_Settings())
    for service in (app.services.database, app.services.passwords, app.services.compute):
        monkeypatch.setattr(service, "ping", AsyncMock(return_value=True))
    monkeypatch.setattr(app.services.redis, "ping", AsyncMock(side_effect=RuntimeError("probe failed")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.content == b""
    assert "Redis (RuntimeError)" in caplog.text


async def test_documentation_can_be_disabled() -> None:
    app = Application(settings=_Settings(APP_DOCS_ENABLED=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/docs", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
