from unittest.mock import AsyncMock

import httpx
import pytest

from api import __version__
from api.main import Application
from api.settings import _Settings


async def test_liveness_does_not_contact_database(monkeypatch: pytest.MonkeyPatch) -> None:
    app = Application(settings=_Settings())
    ping = AsyncMock(side_effect=AssertionError("Liveness must not access PostgreSQL"))
    monkeypatch.setattr(app.services.database, "ping", ping)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
    ping.assert_not_awaited()


@pytest.mark.parametrize(("available", "status_code"), [(True, 200), (False, 503)])
async def test_readiness_reports_database_state(
    monkeypatch: pytest.MonkeyPatch, available: bool, status_code: int
) -> None:
    app = Application(settings=_Settings())
    ping = AsyncMock(return_value=available)
    monkeypatch.setattr(app.services.database, "ping", ping)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    expected = "ok" if available else "unavailable"
    assert response.status_code == status_code
    assert response.json() == {"status": expected, "version": __version__, "database": expected}
    ping.assert_awaited_once_with()


async def test_documentation_can_be_disabled() -> None:
    app = Application(settings=_Settings(APP_DOCS_ENABLED=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/docs", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
