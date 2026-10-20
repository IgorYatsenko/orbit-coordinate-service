import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.services import Services
from api.settings import _Settings


async def test_database_session_requires_startup() -> None:
    database = Services(config=_Settings()).database
    with pytest.raises(RuntimeError, match="has not been started"):
        async with database.session():
            pytest.fail("An uninitialized database must not create a transaction")


async def test_healthcheck_has_an_overall_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    database = Services(config=_Settings(APP_DB_HEALTHCHECK_TIMEOUT_SEC=0.01)).database
    blocked = asyncio.Event()

    @asynccontextmanager
    async def blocked_session() -> AsyncGenerator[AsyncSession]:
        await blocked.wait()
        yield AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(database, "session", blocked_session)
    assert await database.ping() is False
