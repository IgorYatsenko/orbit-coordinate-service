import asyncio

from api.services import Services
from api.settings import get_settings
from dev.project_user import create_user_setup
from dev.settings import DevSettings
from models.pydantic.auth import LoginRequest


async def main() -> None:
    settings = DevSettings()
    services = Services(config=get_settings())
    try:
        await services.database.start()
        created = await create_user_setup(
            services=services,
            credentials=LoginRequest(username=settings.APP_DEV_USERNAME, password=settings.APP_DEV_PASSWORD),
        )
        print("Demo user created" if created else "Demo user already exists; kept unchanged")
    finally:
        await services.database.stop()


if __name__ == "__main__":
    asyncio.run(main())
