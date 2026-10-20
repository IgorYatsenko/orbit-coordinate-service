import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from api.logging import configure_logging
from api.settings import get_settings
from models.sqlalchemy import SQLAlchemyBase

config = context.config
target_metadata = SQLAlchemyBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = get_settings()
    configure_logging(level=settings.APP_LOG_LEVEL)
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={
            "timeout": settings.APP_DB_CONNECT_TIMEOUT_SEC,
            "server_settings": {"statement_timeout": str(round(settings.APP_DB_STATEMENT_TIMEOUT_SEC * 1000))},
        },
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
