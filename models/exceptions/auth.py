from models.exceptions.base import ApplicationError


class AuthenticationFailed(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Invalid credentials or access token")


class AuthenticationBusy(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Password verification capacity is busy; retry later")


class RateLimitExceeded(ApplicationError):
    def __init__(self, retry_after_sec: int) -> None:
        super().__init__("Request rate limit exceeded")
        self.retry_after_sec = retry_after_sec
