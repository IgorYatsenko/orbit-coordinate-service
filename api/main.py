import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from asyncpg import PostgresError
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from api import __version__
from api.exception_handlers import (
    application_error_handler,
    calculation_error_handler,
    database_error_handler,
    request_validation_error_handler,
)
from api.middleware import MetricsMiddleware, RequestBodyLimitMiddleware
from api.router import router
from api.services import Services
from api.settings import _Settings, get_settings
from models.exceptions.base import ApplicationError
from models.exceptions.orbits import CalculationError
from models.pydantic.errors import ErrorResponse

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
            responses={413: {"model": ErrorResponse, "description": "Request body exceeds the configured size limit"}},
        )
        self.state.services = self.services
        self.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=config.APP_HTTP_MAX_BODY_BYTES)
        if self.services.metrics is not None:
            self.add_middleware(MetricsMiddleware, metrics=self.services.metrics)
        self.add_exception_handler(RequestValidationError, request_validation_error_handler)
        self.add_exception_handler(ApplicationError, application_error_handler)
        self.add_exception_handler(CalculationError, calculation_error_handler)
        self.add_exception_handler(SQLAlchemyError, database_error_handler)
        self.add_exception_handler(PostgresError, database_error_handler)
        self.include_router(router)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        async with self.services.lifespan():
            logger.info("Application %s started", __version__)
            yield
        logger.info("Application stopped")


def create_app() -> Application:
    return Application()
