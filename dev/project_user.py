from api.db import users
from api.services import Services
from models.pydantic.auth import LoginRequest


async def create_user_setup(*, services: Services, credentials: LoginRequest) -> bool:
    encoded = await services.passwords.hash(credentials.password.get_secret_value())
    async with services.database.session() as session:
        user_id = await users.create_if_missing(session, username=credentials.username, password_hash=encoded)
    return user_id is not None
