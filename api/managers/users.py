from sqlalchemy.exc import IntegrityError

from api.db import users
from api.db.errors import is_unique_violation
from api.services.passwords import Passwords
from api.services.postgresql import PostgreSQL
from models.pydantic.auth import UserCredentials, UserResponse


class UserManager:
    """Account administration is available only through the local CLI."""

    def __init__(self, *, database: PostgreSQL, passwords: Passwords) -> None:
        self._database = database
        self._passwords = passwords

    async def create(self, credentials: UserCredentials) -> UserResponse:
        encoded = await self._passwords.hash(credentials.password.get_secret_value())
        try:
            async with self._database.session() as session:
                result = UserResponse.model_validate(
                    await users.create(session, username=credentials.username, password_hash=encoded)
                )
            return result
        except IntegrityError as exc:
            if is_unique_violation(exc, constraint="uq_users_username"):
                raise ValueError("Username already exists") from exc
            raise

    async def set_password(self, credentials: UserCredentials) -> None:
        encoded = await self._passwords.hash(credentials.password.get_secret_value())
        async with self._database.session() as session:
            if await users.set_password(session, username=credentials.username, password_hash=encoded) is None:
                raise ValueError("User not found")

    async def disable(self, username: str) -> None:
        async with self._database.session() as session:
            if await users.disable(session, username=username) is None:
                raise ValueError("User not found")
