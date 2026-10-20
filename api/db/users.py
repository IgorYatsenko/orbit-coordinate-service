from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.sqlalchemy import User


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == username))


async def get_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.scalar(select(User).where(User.id == user_id))


async def create_if_missing(session: AsyncSession, *, username: str, password_hash: str) -> UUID | None:
    return await session.scalar(
        insert(User)
        .values(username=username, password_hash=password_hash)
        .on_conflict_do_nothing(constraint="uq_users_username")
        .returning(User.id)
    )
