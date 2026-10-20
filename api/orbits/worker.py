import os
import resource
import sys
from dataclasses import dataclass
from multiprocessing.synchronize import Barrier
from time import perf_counter

from models.pydantic import CoordinateRequest


@dataclass(frozen=True)
class CalculationResult:
    payload: bytes
    point_count: int
    duration_sec: float
    peak_rss_bytes: int = 0


def configure_numeric_threads(numeric_threads: int) -> None:
    # NumPy is imported only after native runtime thread limits are configured.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = str(numeric_threads)


def initialize_worker(numeric_threads: int, barrier: Barrier, start_timeout_sec: float) -> None:
    configure_numeric_threads(numeric_threads)
    from api.orbits.core import get_timescale

    get_timescale()
    barrier.wait(timeout=start_timeout_sec)


def probe_worker() -> int:
    return os.getpid()


def run_calculation(request: CoordinateRequest, chunk_points: int) -> CalculationResult:
    from api.orbits.core import calculate_coordinates

    started = perf_counter()
    response = calculate_coordinates(request, chunk_points=chunk_points)
    payload = response.model_dump_json().encode()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return CalculationResult(
        payload=payload,
        point_count=response.point_count,
        duration_sec=perf_counter() - started,
        peak_rss_bytes=int(rss if sys.platform == "darwin" else rss * 1024),
    )
