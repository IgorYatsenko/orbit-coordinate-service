import logging

from api.services.compute import Compute
from models.pydantic import CalculationResult, CoordinateRequest

logger = logging.getLogger(__name__)


class OrbitManager:
    def __init__(self, *, compute: Compute, max_points: int) -> None:
        self._compute = compute
        self.max_points = max_points

    async def calculate(self, request: CoordinateRequest) -> CalculationResult:
        result = await self._compute.calculate(request)
        logger.info(
            "Trajectory calculated: points=%s calculation_sec=%.6f response_bytes=%s worker_peak_rss_bytes=%s",
            result.point_count,
            result.duration_sec,
            len(result.payload),
            result.peak_rss_bytes,
        )
        return result
