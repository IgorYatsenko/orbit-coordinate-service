from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.sqlalchemy import User


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == username))


async def get_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.scalar(select(User).where(User.id == user_id))


async def create(session: AsyncSession, *, username: str, password_hash: str) -> User:
    result = await session.scalars(insert(User).values(username=username, password_hash=password_hash).returning(User))
    return result.one()


async def set_password(session: AsyncSession, *, username: str, password_hash: str) -> UUID | None:
    return await session.scalar(
        update(User)
        .where(User.username == username)
        .values(password_hash=password_hash, token_version=User.token_version + 1)
        .returning(User.id)
    )


async def disable(session: AsyncSession, *, username: str) -> UUID | None:
    return await session.scalar(
        update(User).where(User.username == username).values(is_active=False).returning(User.id)
    )
