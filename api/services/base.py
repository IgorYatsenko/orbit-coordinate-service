from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager


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

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            for service in self._services:
                stack.push_async_callback(service.stop)
                await service.start()
            yield
