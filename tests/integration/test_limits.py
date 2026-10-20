import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.services import Services
from api.settings import _Settings

pytestmark = pytest.mark.integration


async def test_statement_timeout_is_applied_and_transaction_recovers(app_settings: _Settings) -> None:
    config = app_settings.model_copy(update={"APP_DB_STATEMENT_TIMEOUT_SEC": 0.05})
    services = Services(config=config)
    async with services.lifespan():
        with pytest.raises(DBAPIError) as error:
            async with services.database.session() as session:
                await session.execute(text("SELECT pg_sleep(1)"))
        assert "statement timeout" in str(error.value)
        assert await services.database.ping() is True
