import asyncio
import hashlib
import math
import os
import platform
import statistics
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.orbits.worker import configure_numeric_threads, run_calculation
from api.settings import get_settings
from models.pydantic import CoordinateRequest


class BenchmarkSettings(BaseSettings):
    APP_BENCH_MODE: Literal["core", "http"] = Field(default="http", description="Direct worker or HTTP measurement.")
    APP_BENCH_BASE_URL: str = Field(default="http://127.0.0.1:8000", description="Running API URL.")
    APP_BENCH_INPUT: Path = Field(default=Path("examples/request-omm.json"), description="Fixed input request file.")
    APP_BENCH_OUTPUT: Path = Field(
        default=Path("artifacts/benchmark.json"), description="Machine-readable report file."
    )
    APP_BENCH_REPETITIONS: int = Field(default=5, ge=1, description="Sequential repetitions per scenario.")
    APP_BENCH_CONCURRENCY: int = Field(default=4, ge=1, description="Simultaneous requests in the day/1s burst.")
    APP_BENCH_TIMEOUT_SEC: float = Field(default=60, gt=0, description="Client timeout per HTTP operation.")
    APP_BENCH_HEALTH_INTERVAL_SEC: float = Field(
        default=0.05, gt=0, description="Delay between pairs of health probes."
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)


class Sample(BaseModel):
    status: int
    elapsed_sec: float
    compute_sec: float | None
    response_bytes: int
    worker_peak_rss_bytes: int | None = None


class Scenario(BaseModel):
    name: str
    point_count: int
    samples: list[Sample]


class HealthSample(BaseModel):
    path: str
    status: int
    elapsed_sec: float


class Report(BaseModel):
    recorded_at: datetime
    mode: str
    python: str
    platform: str
    cpu_count: int | None
    dependencies: dict[str, str]
    input_sha256: str
    compute_settings: dict[str, int | float]
    benchmark_settings: BenchmarkSettings
    scenarios: list[Scenario]
    health: list[HealthSample]


def _scenarios(request: CoordinateRequest) -> list[tuple[str, CoordinateRequest]]:
    result = []
    for hours, step in ((1, 60), (1, 1), (24, 60), (24, 1)):
        fields = {**request.model_dump(), "end": request.start + timedelta(hours=hours), "step_seconds": step}
        result.append((f"{hours}h_step_{step}s", CoordinateRequest.model_validate(fields)))
    return result


def _print_scenario(scenario: Scenario) -> None:
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


def measure_core(settings: BenchmarkSettings, request: CoordinateRequest) -> list[Scenario]:
    config = get_settings()
    configure_numeric_threads(config.APP_COMPUTE_NUMERIC_THREADS)
    run_calculation(CoordinateRequest.model_validate({**request.model_dump(), "end": request.start}), 1)
    scenarios = []
    for name, payload in _scenarios(request):
        samples = []
        for _ in range(settings.APP_BENCH_REPETITIONS):
            started = perf_counter()
            result = run_calculation(payload, config.APP_COMPUTE_CHUNK_POINTS)
            samples.append(
                Sample(
                    status=200,
                    elapsed_sec=perf_counter() - started,
                    compute_sec=result.duration_sec,
                    response_bytes=len(result.payload),
                    worker_peak_rss_bytes=result.peak_rss_bytes,
                )
            )
        scenario = Scenario(name=name, point_count=payload.point_count, samples=samples)
        _print_scenario(scenario)
        scenarios.append(scenario)
    return scenarios


async def _send(client: httpx.AsyncClient, request: CoordinateRequest) -> Sample:
    started = perf_counter()
    response = await client.post(
        "/api/v1/orbits/coordinates", content=request.model_dump_json(), headers={"Content-Type": "application/json"}
    )
    elapsed = perf_counter() - started
    timing = response.headers.get("server-timing")
    compute = float(timing.partition("dur=")[2]) / 1000 if timing else None
    return Sample(
        status=response.status_code, elapsed_sec=elapsed, compute_sec=compute, response_bytes=len(response.content)
    )


async def _monitor_health(
    client: httpx.AsyncClient, stopped: asyncio.Event, interval: float, samples: list[HealthSample]
) -> None:
    async def probe(path: str) -> None:
        started = perf_counter()
        response = await client.get(path)
        samples.append(HealthSample(path=path, status=response.status_code, elapsed_sec=perf_counter() - started))

    while not stopped.is_set():
        await asyncio.gather(probe("/health/live"), probe("/health/ready"))
        try:
            async with asyncio.timeout(interval):
                await stopped.wait()
        except TimeoutError:
            pass


async def measure_http(
    settings: BenchmarkSettings, request: CoordinateRequest
) -> tuple[list[Scenario], list[HealthSample]]:
    health: list[HealthSample] = []
    async with httpx.AsyncClient(
        base_url=settings.APP_BENCH_BASE_URL, timeout=settings.APP_BENCH_TIMEOUT_SEC
    ) as client:
        warmup = await _send(client, CoordinateRequest.model_validate({**request.model_dump(), "end": request.start}))
        if warmup.status != 200:
            raise RuntimeError(f"Warmup failed with HTTP {warmup.status}")
        stopped = asyncio.Event()
        monitor = asyncio.create_task(_monitor_health(client, stopped, settings.APP_BENCH_HEALTH_INTERVAL_SEC, health))
        scenarios = []
        try:
            for name, payload in _scenarios(request):
                samples = [await _send(client, payload) for _ in range(settings.APP_BENCH_REPETITIONS)]
                scenario = Scenario(name=name, point_count=payload.point_count, samples=samples)
                scenarios.append(scenario)
                _print_scenario(scenario)
            _, payload = _scenarios(request)[-1]
            burst = await asyncio.gather(*(_send(client, payload) for _ in range(settings.APP_BENCH_CONCURRENCY)))
            scenario = Scenario(name="concurrent_24h_step_1s", point_count=payload.point_count, samples=list(burst))
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
    report = Report(
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
