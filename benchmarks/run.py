import asyncio
import hashlib
import math
import os
import platform
import statistics
import sys
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from time import perf_counter

import httpx
from pydantic import TypeAdapter, ValidationError

from api.orbits.worker import CalculationWorker
from api.settings import get_settings
from benchmarks.settings import BenchmarkSettings
from models.pydantic import CalculationErrorResponse, CoordinateRequest
from models.pydantic.auth import TokenResponse
from models.pydantic.benchmarks import BenchmarkHealthSample, BenchmarkReport, BenchmarkSample, BenchmarkScenario
from models.pydantic.errors import ErrorResponse


def _scenarios(request: CoordinateRequest, *, max_points: int) -> list[tuple[str, CoordinateRequest]]:
    result = []
    for hours, step in ((1, 60), (1, 1), (24, 60), (24, 1), (48, 1)):
        fields = {**request.model_dump(), "end": request.start + timedelta(hours=hours), "step_seconds": step}
        result.append((f"{hours}h_step_{step}s", CoordinateRequest.model_validate(fields)))
    fields = {
        **request.model_dump(),
        "end": request.start + timedelta(seconds=max_points - 1),
        "step_seconds": 1,
    }
    result.append(("max_points_step_1s", CoordinateRequest.model_validate(fields)))
    return result


def _print_scenario(scenario: BenchmarkScenario) -> None:
    successful = [sample for sample in scenario.samples if sample.status == 200]
    if successful:
        timings = sorted(sample.elapsed_sec * 1000 for sample in successful)
        p95 = timings[math.ceil(len(timings) * 0.95) - 1]
        print(
            f"{scenario.name}: points={scenario.point_count} success={len(successful)}/{len(scenario.samples)} "
            f"median_ms={statistics.median(timings):.2f} p95_ms={p95:.2f} bytes={successful[0].response_bytes}",
            flush=True,
        )
    else:
        print(f"{scenario.name}: no successful responses", flush=True)
    failures = Counter(
        sample.error_code or f"http_{sample.status}" for sample in scenario.samples if sample.status != 200
    )
    if failures:
        print(f"{scenario.name}: failures={dict(failures)}", flush=True)


def measure_core(
    settings: BenchmarkSettings, request: CoordinateRequest, *, scenarios: list[BenchmarkScenario]
) -> None:
    config = get_settings()
    worker = CalculationWorker(
        chunk_points=config.APP_COMPUTE_CHUNK_POINTS, numeric_threads=config.APP_COMPUTE_NUMERIC_THREADS
    )
    worker.run(CoordinateRequest.model_validate({**request.model_dump(), "end": request.start}))
    for name, payload in _scenarios(request, max_points=config.APP_COMPUTE_MAX_POINTS):
        scenario = BenchmarkScenario(name=name, point_count=payload.point_count, samples=[])
        scenarios.append(scenario)
        for _ in range(settings.APP_BENCH_REPETITIONS):
            started = perf_counter()
            result = worker.run(payload)
            scenario.samples.append(
                BenchmarkSample(
                    status=200,
                    elapsed_sec=perf_counter() - started,
                    compute_sec=result.duration_sec,
                    response_bytes=len(result.payload),
                    worker_peak_rss_bytes=result.peak_rss_bytes,
                )
            )
        _print_scenario(scenario)


async def _send(client: httpx.AsyncClient, request: CoordinateRequest) -> BenchmarkSample:
    started = perf_counter()
    try:
        response = await client.post(
            "/api/v1/orbits/coordinates",
            content=request.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
    except httpx.TransportError as error:
        return BenchmarkSample(
            status=None,
            elapsed_sec=perf_counter() - started,
            compute_sec=None,
            response_bytes=0,
            error_code="request_timeout" if isinstance(error, httpx.TimeoutException) else "transport_error",
        )
    elapsed = perf_counter() - started
    timing = response.headers.get("server-timing")
    compute = float(timing.partition("dur=")[2]) / 1000 if timing else None
    error_code = None
    if response.is_error:
        try:
            error_code = (
                TypeAdapter(CalculationErrorResponse | ErrorResponse).validate_json(response.content).detail.code
            )
        except ValidationError:
            error_code = "unstructured_error"
    return BenchmarkSample(
        status=response.status_code,
        elapsed_sec=elapsed,
        compute_sec=compute,
        response_bytes=len(response.content),
        error_code=error_code,
    )


async def _monitor_health(
    client: httpx.AsyncClient, stopped: asyncio.Event, interval: float, samples: list[BenchmarkHealthSample]
) -> None:
    async def probe(path: str) -> None:
        started = perf_counter()
        error_code = None
        status = None
        try:
            response = await client.get(path)
            status = response.status_code
        except httpx.TransportError as error:
            error_code = "request_timeout" if isinstance(error, httpx.TimeoutException) else "transport_error"
        samples.append(
            BenchmarkHealthSample(path=path, status=status, elapsed_sec=perf_counter() - started, error_code=error_code)
        )

    while not stopped.is_set():
        await asyncio.gather(probe("/health/live"), probe("/health/ready"))
        try:
            async with asyncio.timeout(interval):
                await stopped.wait()
        except TimeoutError:
            pass


async def measure_http(
    settings: BenchmarkSettings,
    request: CoordinateRequest,
    *,
    scenarios: list[BenchmarkScenario],
    health: list[BenchmarkHealthSample],
) -> None:
    inputs = _scenarios(request, max_points=get_settings().APP_COMPUTE_MAX_POINTS)
    async with httpx.AsyncClient(
        base_url=settings.APP_BENCH_BASE_URL, timeout=settings.APP_BENCH_TIMEOUT_SEC
    ) as client:
        if not settings.APP_BENCH_USERNAME or not settings.APP_BENCH_PASSWORD.get_secret_value():
            raise ValueError("HTTP measurements require APP_BENCH_USERNAME and APP_BENCH_PASSWORD")
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "username": settings.APP_BENCH_USERNAME,
                "password": settings.APP_BENCH_PASSWORD.get_secret_value(),
            },
        )
        login.raise_for_status()
        token = TokenResponse.model_validate_json(login.content)
        client.headers["Authorization"] = f"Bearer {token.access_token}"
        warmup = await _send(client, CoordinateRequest.model_validate({**request.model_dump(), "end": request.start}))
        if warmup.status != 200:
            raise RuntimeError(f"Warmup failed: {warmup.error_code or warmup.status}")
        stopped = asyncio.Event()
        monitor = asyncio.create_task(_monitor_health(client, stopped, settings.APP_BENCH_HEALTH_INTERVAL_SEC, health))
        try:
            for name, payload in inputs:
                scenario = BenchmarkScenario(name=name, point_count=payload.point_count, samples=[])
                scenarios.append(scenario)
                for _ in range(settings.APP_BENCH_REPETITIONS):
                    scenario.samples.append(await _send(client, payload))
                _print_scenario(scenario)
            _, payload = inputs[-1]
            scenario = BenchmarkScenario(name="concurrent_max_points", point_count=payload.point_count, samples=[])
            scenarios.append(scenario)
            async with asyncio.TaskGroup() as tasks:

                async def measure() -> None:
                    scenario.samples.append(await _send(client, payload))

                for _ in range(settings.APP_BENCH_CONCURRENCY):
                    tasks.create_task(measure())
            _print_scenario(scenario)
        finally:
            stopped.set()
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor


def main() -> None:
    settings = BenchmarkSettings()
    source = settings.APP_BENCH_INPUT.read_bytes()
    request = CoordinateRequest.model_validate_json(source)
    config = get_settings()
    report = BenchmarkReport(
        recorded_at=datetime.now(UTC),
        mode=settings.APP_BENCH_MODE,
        python=sys.version,
        platform=platform.platform(),
        cpu_count=os.cpu_count(),
        dependencies={name: version(name) for name in ("orbit-coordinate-service", "skyfield", "sgp4", "numpy")},
        input_sha256=hashlib.sha256(source).hexdigest(),
        compute_settings={
            key: value
            for key, value in config.model_dump().items()
            if key.startswith("APP_COMPUTE_") or key == "APP_HTTP_WORKERS"
        },
        benchmark_settings=settings,
        scenarios=[],
        health=[],
    )
    try:
        if settings.APP_BENCH_MODE == "core":
            measure_core(settings, request, scenarios=report.scenarios)
        else:
            asyncio.run(measure_http(settings, request, scenarios=report.scenarios, health=report.health))
        report.completed = True
    except (Exception, KeyboardInterrupt) as error:
        report.failure = type(error).__name__
        raise
    finally:
        settings.APP_BENCH_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        settings.APP_BENCH_OUTPUT.write_text(report.model_dump_json(indent=2) + "\n")
        print(f"Report saved: {settings.APP_BENCH_OUTPUT}")


if __name__ == "__main__":
    main()
