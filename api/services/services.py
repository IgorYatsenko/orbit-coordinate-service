from api.services.base import BaseServiceHub
from api.services.postgresql import PostgreSQL
from api.settings import _Settings


class Services(BaseServiceHub):
    def __init__(self, *, config: _Settings) -> None:
        self.config = config
        self.database = PostgreSQL(
            url=config.database_url,
            pool_size=config.APP_DB_POOL_SIZE,
            max_overflow=config.APP_DB_MAX_OVERFLOW,
            pool_timeout_sec=config.APP_DB_POOL_TIMEOUT_SEC,
            connect_timeout_sec=config.APP_DB_CONNECT_TIMEOUT_SEC,
            statement_timeout_sec=config.APP_DB_STATEMENT_TIMEOUT_SEC,
            healthcheck_timeout_sec=config.APP_DB_HEALTHCHECK_TIMEOUT_SEC,
        )
        super().__init__(services=(self.database,))
