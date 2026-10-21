import asyncio

from api.db.users import create_if_missing
from api.services import Services
from api.settings import get_settings


async def add_test_user() -> None:
    services = Services(config=get_settings())
    try:
        await services.database.start()
        encoded = await services.passwords.hash("test-password")
        async with services.database.session() as session:
            user_id = await create_if_missing(session, username="testuser", password_hash=encoded)
        print("Test user created" if user_id else "Test user already exists")
    finally:
        await services.database.stop()


def main() -> None:
    asyncio.run(add_test_user())


if __name__ == "__main__":
    main()
