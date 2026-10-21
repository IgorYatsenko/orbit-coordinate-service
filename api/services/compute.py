import asyncio
import logging
import multiprocessing
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from time import monotonic
from typing import cast

from api.orbits.worker import CalculationWorker
from api.services.base import BaseService
from models.exceptions import ComputeBusy, ComputeTimeout, ComputeUnavailable
from models.pydantic import CalculationResult, CoordinateRequest

logger = logging.getLogger(__name__)


def _consume_exception[T](future: asyncio.Future[T]) -> None:
    if not future.cancelled():
        future.exception()


class Compute(BaseService):
    def __init__(
        self,
        *,
        workers: int,
        chunk_points: int,
        numeric_threads: int,
        timeout_sec: float,
        stall_timeout_sec: float,
        start_timeout_sec: float,
        healthcheck_timeout_sec: float,
    ) -> None:
        self._workers = workers
        self._chunk_points = chunk_points
        self._numeric_threads = numeric_threads
        self._timeout_sec = timeout_sec
        self._stall_timeout_sec = stall_timeout_sec
        self._start_timeout_sec = start_timeout_sec
        self._healthcheck_timeout_sec = healthcheck_timeout_sec
        self._executor: ProcessPoolExecutor | None = None
        self._in_flight: dict[Future[object], float] = {}
        self._stalled = False
        self._ready = False
        self._broken = False
        self._health_probe: asyncio.Future[int] | None = None

    async def start(self) -> None:
        context = multiprocessing.get_context("spawn")
        self._broken = False
        self._executor = ProcessPoolExecutor(
            max_workers=self._workers,
            mp_context=context,
            initializer=CalculationWorker.initialize,
            initargs=(
                self._chunk_points,
                self._numeric_threads,
                context.Barrier(self._workers),
                self._start_timeout_sec,
            ),
        )
        probes = [self._submit(False, CalculationWorker.probe) for _ in range(self._workers)]
        async with asyncio.timeout(self._start_timeout_sec):
            await asyncio.gather(*(asyncio.shield(probe) for probe in probes))
        self._ready = True
        logger.info("Calculation pool started: workers=%s chunk_points=%s", self._workers, self._chunk_points)

    async def stop(self) -> None:
        self._ready = False
        self._health_probe = None
        executor, self._executor = self._executor, None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
        self._in_flight.clear()
        self._stalled = False

    def _has_stalled_tasks(self) -> bool:
        age = monotonic() - min(self._in_flight.values()) if self._in_flight else 0.0
        stalled = age >= self._stall_timeout_sec
        if stalled and not self._stalled:
            logger.error("Calculation pool stalled: oldest_task_sec=%.3f limit_sec=%s", age, self._stall_timeout_sec)
        elif self._stalled and not stalled:
            logger.info("Calculation pool recovered after overdue tasks completed")
        self._stalled = stalled
        return stalled

    def _submit[**P, R](
        self, count_capacity: bool, function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> asyncio.Future[R]:
        if self._executor is None or self._broken:
            raise ComputeUnavailable("Calculation pool is unavailable")
        if count_capacity and len(self._in_flight) >= self._workers:
            raise ComputeBusy("All calculation processes are occupied")
        loop = asyncio.get_running_loop()
        try:
            future = self._executor.submit(function, *args, **kwargs)
        except BrokenProcessPool as error:
            self._broken = True
            raise ComputeUnavailable("Calculation pool is broken") from error
        # Only calculations consume request capacity; at most one shared health probe can also be queued.
        tracked = cast(Future[object], future)
        if count_capacity:
            self._in_flight[tracked] = monotonic()

        def completed(result: Future[R]) -> None:
            broken = not result.cancelled() and isinstance(result.exception(), BrokenProcessPool)
            loop.call_soon_threadsafe(self._complete, tracked, broken)

        future.add_done_callback(completed)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(_consume_exception)
        return wrapped

    def _complete(self, future: Future[object], broken: bool) -> None:
        self._in_flight.pop(future, None)
        if broken:
            self._broken = True
            logger.error("Calculation process exited unexpectedly; application restart is required")

    async def calculate(self, request: CoordinateRequest) -> CalculationResult:
        if not self._ready:
            raise ComputeUnavailable("Calculation pool is not ready")
        if self._has_stalled_tasks():
            raise ComputeUnavailable("A calculation is overdue; wait for completion or restart the application")
        future = self._submit(True, CalculationWorker.execute, request)
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await asyncio.shield(future)
        except TimeoutError as error:
            raise ComputeTimeout(
                "Calculation wait deadline exceeded; its process remains occupied until completion"
            ) from error
        except BrokenProcessPool as error:
            raise ComputeUnavailable("Calculation process exited unexpectedly") from error

    async def ping(self) -> bool:
        if not self._ready or self._broken or self._has_stalled_tasks():
            return False
        if self._health_probe is None and len(self._in_flight) >= self._workers:
            return True
        try:
            if self._health_probe is None:
                self._health_probe = self._submit(False, CalculationWorker.probe)
            future = self._health_probe
            async with asyncio.timeout(self._healthcheck_timeout_sec):
                await asyncio.shield(future)
            return True
        except (TimeoutError, BrokenProcessPool, ComputeUnavailable):
            return False
        finally:
            if self._health_probe is not None and self._health_probe.done():
                self._health_probe = None
