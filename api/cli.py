import argparse
import asyncio
import getpass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from api.managers.users import UserManager
from api.services import Services
from api.settings import get_settings
from models.exceptions.access import DatabaseUnavailable
from models.pydantic.auth import UserCredentials, Username


async def run(command: str, username: str, credentials: UserCredentials | None) -> None:
    services = Services(config=get_settings())
    manager = UserManager(database=services.database, passwords=services.passwords)
    try:
        await services.database.start()
        if command == "create-user" and credentials is not None:
            user = await manager.create(credentials)
            print(f"User created: {user.username} ({user.id})")
        elif command == "set-password" and credentials is not None:
            await manager.set_password(credentials)
            print(f"Password changed and previous tokens revoked: {username}")
        elif command == "disable-user":
            await manager.disable(username)
            print(f"User disabled: {username}")
        else:
            raise ValueError("Password credentials are required")
    finally:
        await services.database.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage local service accounts; passwords are never command arguments."
    )
    parser.add_argument("command", choices=("create-user", "set-password", "disable-user"))
    parser.add_argument("username")
    arguments = parser.parse_args()
    try:
        username = TypeAdapter(Username).validate_python(arguments.username)
        credentials = None
        if arguments.command != "disable-user":
            password = getpass.getpass("Password (12–128 characters): ")
            confirmation = getpass.getpass("Repeat password: ")
            if password != confirmation:
                raise ValueError("Passwords do not match")
            credentials = UserCredentials(username=username, password=password)
        asyncio.run(run(arguments.command, username, credentials))
    except ValidationError:
        parser.exit(
            2, "Invalid configuration or credentials; username: 3–64 ASCII characters, password: 12–128 characters.\n"
        )
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except (SQLAlchemyError, OSError, TimeoutError, DatabaseUnavailable) as exc:
        parser.exit(1, f"Database operation failed ({type(exc).__name__}); check configuration and migrations.\n")


if __name__ == "__main__":
    main()
