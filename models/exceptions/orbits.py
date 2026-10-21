from datetime import datetime

from models.exceptions.base import ApplicationError


class CalculationError(ApplicationError):
    """An expected failure of the trajectory calculation operation."""


class OrbitCalculationError(CalculationError):
    def __init__(self, message: str, time: datetime | None = None) -> None:
        self.time = time
        super().__init__(message, time)

    def __str__(self) -> str:
        return str(self.args[0])


class PointLimitExceeded(CalculationError):
    pass


class ComputeBusy(CalculationError):
    pass


class ComputeUnavailable(CalculationError):
    pass


class ComputeTimeout(CalculationError):
    pass
