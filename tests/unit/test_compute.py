import asyncio
from collections.abc import AsyncGenerator, Callable
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from typing import cast
from unittest.mock import Mock

import pytest

from api.services.compute import Compute
from models.exceptions import ComputeBusy, ComputeTimeout, ComputeUnavailable
from models.pydantic import CalculationResult, CoordinateRequest


class ControlledExecutor:
    def __init__(self) -> None:
        self.pending: list[Future[object]] = []
        self.broken = False
        self.closed = False

    def submit[**P, R](self, function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        if self.broken:
            raise BrokenProcessPool("Test process exited")
        future = Future[R]()
        self.pending.append(cast(Future[object], future))
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.closed = True
        for future in self.pending:
            if not future.done():
                future.cancel()


@pytest.fixture
async def pool(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[tuple[Compute, ControlledExecutor]]:
    executor = ControlledExecutor()
    monkeypatch.setattr("api.services.compute.ProcessPoolExecutor", lambda **kwargs: executor)
    monkeypatch.setattr("api.services.compute.multiprocessing.get_context", lambda _: Mock())
    compute = Compute(
        workers=1,
        chunk_points=16,
        numeric_threads=1,
        timeout_sec=0.02,
        start_timeout_sec=1,
        healthcheck_timeout_sec=0.02,
    )
    starting = asyncio.create_task(compute.start())
    await asyncio.sleep(0)
    executor.pending[0].set_result(1001)
    await starting
    try:
        yield compute, executor
    finally:
        await compute.stop()
    assert executor.closed


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancel_or_timeout_retains_slot_until_process_completion(
    pool: tuple[Compute, ControlledExecutor], omm_request: CoordinateRequest, cancel: bool
) -> None:
    compute, executor = pool
    task = asyncio.create_task(compute.calculate(omm_request))
    await asyncio.sleep(0)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ComputeTimeout):
            await task
    assert await compute.ping() is True  # A busy, functioning pool remains ready.
    with pytest.raises(ComputeBusy):
        await compute.calculate(omm_request)
    executor.pending[-1].set_result(CalculationResult(payload=b"{}", point_count=1, duration_sec=0.01))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    next_task = asyncio.create_task(compute.calculate(omm_request))
    await asyncio.sleep(0)
    executor.pending[-1].set_result(CalculationResult(payload=b"{}", point_count=1, duration_sec=0.01))
    assert (await next_task).point_count == 1


async def test_worker_death_marks_pool_unavailable(
    pool: tuple[Compute, ControlledExecutor], omm_request: CoordinateRequest
) -> None:
    compute, executor = pool
    task = asyncio.create_task(compute.calculate(omm_request))
    await asyncio.sleep(0)
    executor.pending[-1].set_exception(BrokenProcessPool("Test process exited"))
    with pytest.raises(ComputeUnavailable):
        await task
    assert await compute.ping() is False
    with pytest.raises(ComputeUnavailable):
        await compute.calculate(omm_request)


async def test_idle_probe_detects_an_already_broken_executor(pool: tuple[Compute, ControlledExecutor]) -> None:
    compute, executor = pool
    executor.broken = True
    assert await compute.ping() is False


async def test_probe_deadline_keeps_a_single_shared_probe(pool: tuple[Compute, ControlledExecutor]) -> None:
    compute, executor = pool
    assert await compute.ping() is False
    assert not executor.pending[-1].done()
    assert await compute.ping() is False
    assert len(executor.pending) == 2  # Warmup plus one shared probe; no growing health queue.


async def test_health_probe_does_not_reject_a_calculation_in_an_idle_pool(
    pool: tuple[Compute, ControlledExecutor], omm_request: CoordinateRequest
) -> None:
    compute, executor = pool
    probing = asyncio.create_task(compute.ping())
    await asyncio.sleep(0)
    calculation = asyncio.create_task(compute.calculate(omm_request))
    await asyncio.sleep(0)
    assert len(executor.pending) == 3  # Warmup, one probe and one admitted calculation.
    with pytest.raises(ComputeBusy):
        await compute.calculate(omm_request)
    executor.pending[1].set_result(1001)
    assert await probing is True
    executor.pending[2].set_result(CalculationResult(payload=b"{}", point_count=1, duration_sec=0.01))
    assert (await calculation).point_count == 1
