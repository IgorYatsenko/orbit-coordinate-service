import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.services.postgresql import PostgreSQL

pytestmark = pytest.mark.integration


@pytest.fixture
async def probe(database: PostgreSQL) -> AsyncIterator[PostgreSQL]:
    async with database.session() as session:
        await session.execute(text("CREATE TABLE transaction_probe (id integer PRIMARY KEY, value text NOT NULL)"))
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(text("DROP TABLE transaction_probe"))


async def test_successful_transaction_is_committed(probe: PostgreSQL) -> None:
    async with probe.session() as session:
        await session.execute(text("INSERT INTO transaction_probe VALUES (1, 'committed')"))
    async with probe.session() as session:
        assert await session.scalar(text("SELECT value FROM transaction_probe WHERE id = 1")) == "committed"


async def test_application_error_rolls_back_all_writes(probe: PostgreSQL) -> None:
    with pytest.raises(ValueError, match="Abort operation"):
        async with probe.session() as session:
            await session.execute(text("INSERT INTO transaction_probe VALUES (1, 'first')"))
            await session.execute(text("INSERT INTO transaction_probe VALUES (2, 'second')"))
            raise ValueError("Abort operation")
    async with probe.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM transaction_probe")) == 0


async def test_constraint_failure_rolls_back_and_pool_remains_usable(probe: PostgreSQL) -> None:
    with pytest.raises(IntegrityError):
        async with probe.session() as session:
            await session.execute(text("INSERT INTO transaction_probe VALUES (1, 'first')"))
            await session.execute(text("INSERT INTO transaction_probe VALUES (1, 'duplicate')"))
    async with probe.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM transaction_probe")) == 0
    assert await probe.ping() is True


async def test_cancelled_operation_rolls_back_and_releases_connection(probe: PostgreSQL) -> None:
    inserted = asyncio.Event()
    blocked = asyncio.Event()

    async def write_then_wait() -> None:
        async with probe.session() as session:
            await session.execute(text("INSERT INTO transaction_probe VALUES (1, 'cancelled')"))
            inserted.set()
            await blocked.wait()

    task = asyncio.create_task(write_then_wait())
    try:
        await asyncio.wait_for(inserted.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with probe.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM transaction_probe")) == 0
    assert await probe.ping() is True
