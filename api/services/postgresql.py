import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import URL, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.services.base import BaseService
from models.exceptions.access import DatabaseUnavailable

logger = logging.getLogger(__name__)


class PostgreSQL(BaseService):
    def __init__(
        self,
        *,
        url: URL,
        pool_size: int,
        max_overflow: int,
        pool_timeout_sec: float,
        connect_timeout_sec: float,
        statement_timeout_sec: float,
        healthcheck_timeout_sec: float,
    ) -> None:
        self._url = url
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_timeout_sec = pool_timeout_sec
        self._connect_timeout_sec = connect_timeout_sec
        self._statement_timeout_sec = statement_timeout_sec
        self._healthcheck_timeout_sec = healthcheck_timeout_sec
        self._engine: AsyncEngine | None = None
        self._session_maker: async_sessionmaker[AsyncSession] | None = None

    async def start(self) -> None:
        self._engine = create_async_engine(
            url=self._url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout_sec,
            pool_pre_ping=True,
            connect_args={
                "timeout": self._connect_timeout_sec,
                "server_settings": {"statement_timeout": str(round(self._statement_timeout_sec * 1000))},
            },
        )
        self._session_maker = async_sessionmaker(bind=self._engine, expire_on_commit=False)
        async with self.session() as session:
            await session.execute(select(1))
        logger.info("PostgreSQL connection established")

    async def stop(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None
            logger.info("PostgreSQL connection pool disposed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        if self._session_maker is None:
            raise RuntimeError("PostgreSQL service has not been started")
        try:
            async with self._session_maker.begin() as session:
                yield session
        except (OSError, TimeoutError) as exc:
            logger.warning("PostgreSQL connection failed: %s", type(exc).__name__)
            raise DatabaseUnavailable() from exc

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(self._healthcheck_timeout_sec), self.session() as session:
                return (await session.scalar(select(1))) == 1
        except (SQLAlchemyError, OSError, TimeoutError, DatabaseUnavailable) as exc:
            logger.warning("PostgreSQL healthcheck failed: %s", type(exc).__name__)
            return False
