from datetime import datetime


class OrbitCalculationError(Exception):
    def __init__(self, message: str, time: datetime | None = None) -> None:
        self.time = time
        super().__init__(message, time)

    def __str__(self) -> str:
        return str(self.args[0])


class ComputeBusy(Exception):
    pass


class ComputeUnavailable(Exception):
    pass


class ComputeTimeout(Exception):
    pass
