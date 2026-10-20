import asyncio
import hashlib
import math
import os
import platform
import statistics
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from time import perf_counter

import httpx

from api.orbits.worker import CalculationWorker
from api.settings import get_settings
from benchmarks.settings import BenchmarkSettings
from models.pydantic import CoordinateRequest
from models.pydantic.auth import TokenResponse
from models.pydantic.benchmarks import BenchmarkHealthSample, BenchmarkReport, BenchmarkSample, BenchmarkScenario


def _scenarios(request: CoordinateRequest) -> list[tuple[str, CoordinateRequest]]:
    result = []
    for hours, step in ((1, 60), (1, 1), (24, 60), (24, 1)):
        fields = {**request.model_dump(), "end": request.start + timedelta(hours=hours), "step_seconds": step}
        result.append((f"{hours}h_step_{step}s", CoordinateRequest.model_validate(fields)))
    return result


def _print_scenario(scenario: BenchmarkScenario) -> None:
    successful = [sample for sample in scenario.samples if sample.status == 200]
    if successful:
        timings = sorted(sample.elapsed_sec * 1000 for sample in successful)
        p95 = timings[math.ceil(len(timings) * 0.95) - 1]
        print(
            f"{scenario.name}: points={scenario.point_count} success={len(successful)}/{len(scenario.samples)} "
            f"median_ms={statistics.median(timings):.2f} p95_ms={p95:.2f} bytes={successful[0].response_bytes}"
        )
    else:
        print(f"{scenario.name}: no successful responses")


def measure_core(settings: BenchmarkSettings, request: CoordinateRequest) -> list[BenchmarkScenario]:
    config = get_settings()
    worker = CalculationWorker(
        chunk_points=config.APP_COMPUTE_CHUNK_POINTS, numeric_threads=config.APP_COMPUTE_NUMERIC_THREADS
    )
    worker.run(CoordinateRequest.model_validate({**request.model_dump(), "end": request.start}))
    scenarios = []
    for name, payload in _scenarios(request):
        samples = []
        for _ in range(settings.APP_BENCH_REPETITIONS):
            started = perf_counter()
            result = worker.run(payload)
            samples.append(
                BenchmarkSample(
                    status=200,
                    elapsed_sec=perf_counter() - started,
                    compute_sec=result.duration_sec,
                    response_bytes=len(result.payload),
                    worker_peak_rss_bytes=result.peak_rss_bytes,
                )
            )
        scenario = BenchmarkScenario(name=name, point_count=payload.point_count, samples=samples)
        _print_scenario(scenario)
        scenarios.append(scenario)
    return scenarios


async def _send(client: httpx.AsyncClient, request: CoordinateRequest) -> BenchmarkSample:
    started = perf_counter()
    response = await client.post(
        "/api/v1/orbits/coordinates", content=request.model_dump_json(), headers={"Content-Type": "application/json"}
    )
    elapsed = perf_counter() - started
    timing = response.headers.get("server-timing")
    compute = float(timing.partition("dur=")[2]) / 1000 if timing else None
    return BenchmarkSample(
        status=response.status_code, elapsed_sec=elapsed, compute_sec=compute, response_bytes=len(response.content)
    )


async def _monitor_health(
    client: httpx.AsyncClient, stopped: asyncio.Event, interval: float, samples: list[BenchmarkHealthSample]
) -> None:
    async def probe(path: str) -> None:
        started = perf_counter()
        response = await client.get(path)
        samples.append(
            BenchmarkHealthSample(path=path, status=response.status_code, elapsed_sec=perf_counter() - started)
        )

    while not stopped.is_set():
        await asyncio.gather(probe("/health/live"), probe("/health/ready"))
        try:
            async with asyncio.timeout(interval):
                await stopped.wait()
        except TimeoutError:
            pass


async def measure_http(
    settings: BenchmarkSettings, request: CoordinateRequest
) -> tuple[list[BenchmarkScenario], list[BenchmarkHealthSample]]:
    health: list[BenchmarkHealthSample] = []
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
            raise RuntimeError(f"Warmup failed with HTTP {warmup.status}")
        stopped = asyncio.Event()
        monitor = asyncio.create_task(_monitor_health(client, stopped, settings.APP_BENCH_HEALTH_INTERVAL_SEC, health))
        scenarios = []
        try:
            for name, payload in _scenarios(request):
                samples = [await _send(client, payload) for _ in range(settings.APP_BENCH_REPETITIONS)]
                scenario = BenchmarkScenario(name=name, point_count=payload.point_count, samples=samples)
                scenarios.append(scenario)
                _print_scenario(scenario)
            _, payload = _scenarios(request)[-1]
            burst = await asyncio.gather(*(_send(client, payload) for _ in range(settings.APP_BENCH_CONCURRENCY)))
            scenario = BenchmarkScenario(
                name="concurrent_24h_step_1s", point_count=payload.point_count, samples=list(burst)
            )
            scenarios.append(scenario)
            _print_scenario(scenario)
        finally:
            stopped.set()
            await monitor
    return scenarios, health


def main() -> None:
    settings = BenchmarkSettings()
    source = settings.APP_BENCH_INPUT.read_bytes()
    request = CoordinateRequest.model_validate_json(source)
    config = get_settings()
    scenarios, health = (
        (measure_core(settings, request), [])
        if settings.APP_BENCH_MODE == "core"
        else asyncio.run(measure_http(settings, request))
    )
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
        scenarios=scenarios,
        health=health,
    )
    settings.APP_BENCH_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    settings.APP_BENCH_OUTPUT.write_text(report.model_dump_json(indent=2) + "\n")
    print(f"Report saved: {settings.APP_BENCH_OUTPUT}")


if __name__ == "__main__":
    main()
