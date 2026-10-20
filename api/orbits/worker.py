from __future__ import annotations

import os
import resource
import sys
from multiprocessing.synchronize import Barrier
from time import perf_counter
from typing import TYPE_CHECKING, ClassVar

from models.pydantic import CalculationResult, CoordinateRequest

if TYPE_CHECKING:
    from api.orbits.core import OrbitCalculator


class CalculationWorker:
    """Own one calculator; the pool initializer creates one instance in each child."""

    _process_instance: ClassVar[CalculationWorker | None] = None

    def __init__(self, *, chunk_points: int, numeric_threads: int) -> None:
        # NumPy is imported only after native runtime thread limits are configured.
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            os.environ[name] = str(numeric_threads)
        from api.orbits.core import OrbitCalculator

        self._calculator: OrbitCalculator = OrbitCalculator(chunk_points=chunk_points)

    def run(self, request: CoordinateRequest) -> CalculationResult:
        started = perf_counter()
        response = self._calculator.calculate(request)
        payload = response.model_dump_json().encode()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return CalculationResult(
            payload=payload,
            point_count=response.point_count,
            duration_sec=perf_counter() - started,
            peak_rss_bytes=int(rss if sys.platform == "darwin" else rss * 1024),
        )

    @classmethod
    def initialize(cls, chunk_points: int, numeric_threads: int, barrier: Barrier, start_timeout_sec: float) -> None:
        cls._process_instance = cls(chunk_points=chunk_points, numeric_threads=numeric_threads)
        barrier.wait(timeout=start_timeout_sec)

    @classmethod
    def _current(cls) -> CalculationWorker:
        if cls._process_instance is None:
            raise RuntimeError("Calculation process has not been initialized")
        return cls._process_instance

    @classmethod
    def execute(cls, request: CoordinateRequest) -> CalculationResult:
        return cls._current().run(request)

    @classmethod
    def probe(cls) -> int:
        cls._current()
        return os.getpid()
