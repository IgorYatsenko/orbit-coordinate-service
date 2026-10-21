import asyncio
from pathlib import Path

import httpx
import pytest

from benchmarks.run import _monitor_health, _send, main, measure_http
from benchmarks.settings import BenchmarkSettings
from models.pydantic import CoordinateRequest
from models.pydantic.benchmarks import BenchmarkHealthSample, BenchmarkReport, BenchmarkSample, BenchmarkScenario


@pytest.mark.parametrize(
    ("error_type", "code"), [(httpx.ReadTimeout, "request_timeout"), (httpx.ConnectError, "transport_error")]
)
async def test_transport_failure_is_a_measurement(
    omm_request: CoordinateRequest, error_type: type[httpx.TransportError], code: str
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error_type("Test network failure", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="http://test") as client:
        sample = await _send(client, omm_request)
    assert sample.status is None and sample.error_code == code
    assert sample.elapsed_sec >= 0 and sample.compute_sec is None and sample.response_bytes == 0


async def test_health_monitor_records_network_failures() -> None:
    stopped = asyncio.Event()
    samples: list[BenchmarkHealthSample] = []

    def fail(request: httpx.Request) -> httpx.Response:
        stopped.set()
        if request.url.path == "/health/live":
            raise httpx.ReadTimeout("Test timeout", request=request)
        raise httpx.ConnectError("Test connection failure", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="http://test") as client:
        await _monitor_health(client, stopped, 0.01, samples)
    assert {item.path: item.error_code for item in samples} == {
        "/health/live": "request_timeout",
        "/health/ready": "transport_error",
    }
    assert all(item.status is None for item in samples)


async def test_finished_http_run_cancels_an_unresponsive_health_probe(
    monkeypatch: pytest.MonkeyPatch, omm_request: CoordinateRequest
) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "test", "expires_in": 900})
        if request.url.path.startswith("/health/"):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        await asyncio.sleep(0)
        return httpx.Response(200, content=b"{}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="http://test")
    monkeypatch.setattr("benchmarks.run.httpx.AsyncClient", lambda **kwargs: client)
    settings = BenchmarkSettings(
        APP_BENCH_USERNAME="reviewer", APP_BENCH_PASSWORD="password", APP_BENCH_REPETITIONS=1, APP_BENCH_CONCURRENCY=1
    )
    scenarios: list[BenchmarkScenario] = []
    async with asyncio.timeout(1):
        await measure_http(settings, omm_request, scenarios=scenarios, health=[])
    assert entered.is_set() and cancelled.is_set()
    assert len(scenarios) == 7 and all(item.samples[0].status == 200 for item in scenarios)


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_interrupted_run_saves_completed_measurements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, omm_request: CoordinateRequest, error_type: type[BaseException]
) -> None:
    source = tmp_path / "request.json"
    output = tmp_path / "report.json"
    source.write_text(omm_request.model_dump_json())
    monkeypatch.setenv("APP_BENCH_INPUT", str(source))
    monkeypatch.setenv("APP_BENCH_OUTPUT", str(output))

    async def interrupted(
        settings: BenchmarkSettings,
        request: CoordinateRequest,
        *,
        scenarios: list[BenchmarkScenario],
        health: list[BenchmarkHealthSample],
    ) -> None:
        scenarios.append(
            BenchmarkScenario(
                name="partial",
                point_count=request.point_count,
                samples=[BenchmarkSample(status=200, elapsed_sec=1, compute_sec=0.5, response_bytes=10)],
            )
        )
        health.append(
            BenchmarkHealthSample(path="/health/ready", status=None, elapsed_sec=1, error_code="request_timeout")
        )
        raise error_type("private exception details")

    monkeypatch.setattr("benchmarks.run.measure_http", interrupted)
    with pytest.raises(error_type):
        main()
    report = BenchmarkReport.model_validate_json(output.read_text())
    assert report.completed is False and report.failure == error_type.__name__
    assert report.scenarios[0].samples[0].status == 200
    assert report.health[0].error_code == "request_timeout"
    assert "private exception details" not in output.read_text()
