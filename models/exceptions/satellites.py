from models.exceptions.base import ApplicationError


class SatelliteNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Satellite not found")


class SatelliteConflict(ApplicationError):
    def __init__(self) -> None:
        super().__init__("A satellite with this NORAD ID already exists")
