import asyncio
import logging
import multiprocessing
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

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
        start_timeout_sec: float,
        healthcheck_timeout_sec: float,
    ) -> None:
        self._workers = workers
        self._chunk_points = chunk_points
        self._numeric_threads = numeric_threads
        self._timeout_sec = timeout_sec
        self._start_timeout_sec = start_timeout_sec
        self._healthcheck_timeout_sec = healthcheck_timeout_sec
        self._executor: ProcessPoolExecutor | None = None
        self._in_flight = 0
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
        probes = [self._submit(CalculationWorker.probe) for _ in range(self._workers)]
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
        self._in_flight = 0

    def _submit[**P, R](self, function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> asyncio.Future[R]:
        if self._executor is None or self._broken:
            raise ComputeUnavailable("Calculation pool is unavailable")
        if self._in_flight >= self._workers:
            raise ComputeBusy("All calculation processes are occupied")
        loop = asyncio.get_running_loop()
        try:
            future = self._executor.submit(function, *args, **kwargs)
        except BrokenProcessPool as error:
            self._broken = True
            raise ComputeUnavailable("Calculation pool is broken") from error
        self._in_flight += 1

        def completed(result: Future[R]) -> None:
            broken = not result.cancelled() and isinstance(result.exception(), BrokenProcessPool)
            loop.call_soon_threadsafe(self._complete, broken)

        future.add_done_callback(completed)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(_consume_exception)
        return wrapped

    def _complete(self, broken: bool) -> None:
        self._in_flight -= 1
        if broken:
            self._broken = True
            logger.error("Calculation process exited unexpectedly; application restart is required")

    async def calculate(self, request: CoordinateRequest) -> CalculationResult:
        if not self._ready:
            raise ComputeUnavailable("Calculation pool is not ready")
        future = self._submit(CalculationWorker.execute, request)
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
        if not self._ready or self._broken:
            return False
        if self._health_probe is None and self._in_flight >= self._workers:
            return True
        try:
            if self._health_probe is None:
                self._health_probe = self._submit(CalculationWorker.probe)
            future = self._health_probe
            async with asyncio.timeout(self._healthcheck_timeout_sec):
                await asyncio.shield(future)
            return True
        except (TimeoutError, BrokenProcessPool, ComputeUnavailable):
            return False
        finally:
            if self._health_probe is not None and self._health_probe.done():
                self._health_probe = None
