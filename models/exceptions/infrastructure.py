from models.exceptions.base import ApplicationError


class RedisUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Rate limiter is unavailable")


class DatabaseUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Database operation could not be completed")
