import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from api import __version__
from api.exception_handlers import access_error_handler, database_error_handler, request_validation_error_handler
from api.router import router
from api.services import Services
from api.settings import _Settings, get_settings
from models.exceptions.access import AccessError

logger = logging.getLogger(__name__)


class Application(FastAPI):
    def __init__(self, *, settings: _Settings | None = None) -> None:
        config = settings if settings is not None else get_settings()
        self.services = Services(config=config)
        super().__init__(
            title="Orbit Coordinate Service",
            description="Satellite coordinate calculation and metadata registry.",
            version=__version__,
            root_path=config.APP_ROOT_PATH,
            docs_url="/docs" if config.APP_DOCS_ENABLED else None,
            redoc_url=None,
            openapi_url="/openapi.json" if config.APP_DOCS_ENABLED else None,
            lifespan=self._lifespan,
        )
        self.state.services = self.services
        self.add_exception_handler(RequestValidationError, request_validation_error_handler)
        self.add_exception_handler(AccessError, access_error_handler)
        self.add_exception_handler(SQLAlchemyError, database_error_handler)
        self.include_router(router)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        async with self.services.lifespan():
            logger.info("Application %s started", __version__)
            yield
        logger.info("Application stopped")


def create_app() -> Application:
    return Application()
