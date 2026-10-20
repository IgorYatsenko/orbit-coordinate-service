import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_migrations_upgrade_downgrade_and_match_metadata(engine: AsyncEngine, migration_config: Config) -> None:
    def run(connection: Connection) -> None:
        migration_config.attributes["connection"] = connection
        command.upgrade(migration_config, "head")
        command.upgrade(migration_config, "head")
        expected = ScriptDirectory.from_config(migration_config).get_current_head()
        assert expected is not None
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == expected
        command.check(migration_config)
        command.downgrade(migration_config, "base")
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
        command.upgrade(migration_config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == expected

    async with engine.begin() as connection:
        await connection.run_sync(run)
