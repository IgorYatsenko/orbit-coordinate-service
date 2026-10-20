import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

logger = logging.getLogger(__name__)


class BaseService(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Acquire resources and verify connectivity."""

    @abstractmethod
    async def stop(self) -> None:
        """Release resources, including resources from a partial startup."""

    @abstractmethod
    async def ping(self) -> bool:
        """Check whether the service is available."""


class BaseServiceHub:
    def __init__(self, *, services: tuple[BaseService, ...]) -> None:
        self._services = services

    async def healthcheck(self) -> bool:
        results = await asyncio.gather(*(service.ping() for service in self._services), return_exceptions=True)
        for service, result in zip(self._services, results, strict=True):
            if result is not True:
                reason = type(result).__name__ if isinstance(result, BaseException) else "unavailable"
                logger.warning("Service healthcheck failed: %s (%s)", type(service).__name__, reason)
        return all(result is True for result in results)

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            for service in self._services:
                stack.push_async_callback(service.stop)
                await service.start()
            yield
