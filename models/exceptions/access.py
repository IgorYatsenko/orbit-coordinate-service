class AccessError(Exception):
    """An expected failure with a public, non-sensitive message."""


class AuthenticationFailed(AccessError):
    def __init__(self) -> None:
        super().__init__("Invalid credentials or access token")


class AuthenticationBusy(AccessError):
    def __init__(self) -> None:
        super().__init__("Password verification capacity is busy; retry later")


class RedisUnavailable(AccessError):
    def __init__(self) -> None:
        super().__init__("Rate limiter is unavailable")


class DatabaseUnavailable(AccessError):
    def __init__(self) -> None:
        super().__init__("Database operation could not be completed")


class RateLimitExceeded(AccessError):
    def __init__(self, retry_after_sec: int) -> None:
        super().__init__("Request rate limit exceeded")
        self.retry_after_sec = retry_after_sec


class SatelliteNotFound(AccessError):
    def __init__(self) -> None:
        super().__init__("Satellite not found")


class SatelliteConflict(AccessError):
    def __init__(self) -> None:
        super().__init__("A satellite with this NORAD ID already exists")
