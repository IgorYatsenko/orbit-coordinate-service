from pathlib import Path

import httpx
import pytest

from benchmarks.run import _send
from benchmarks.settings import BenchmarkSettings
from models.pydantic import CoordinateRequest
from models.pydantic.benchmarks import BenchmarkConfiguration


def test_benchmark_environment_and_report_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_BENCH_REPETITIONS=2\nAPP_BENCH_MODE=core\nAPP_DB_NAME=ignored\n")
    monkeypatch.setenv("APP_BENCH_REPETITIONS", "3")
    monkeypatch.setenv("APP_BENCH_USERNAME", "a-private-benchmark-account")
    monkeypatch.setenv("APP_BENCH_PASSWORD", "private-benchmark-password")
    settings = BenchmarkSettings()
    assert settings.APP_BENCH_REPETITIONS == 3
    assert settings.APP_BENCH_MODE == "core"
    recorded = BenchmarkConfiguration.model_validate_json(settings.model_dump_json())
    assert recorded.APP_BENCH_REPETITIONS == settings.APP_BENCH_REPETITIONS
    assert recorded.APP_BENCH_INPUT == Path("examples/request-omm.json")
    assert "private-benchmark" not in settings.model_dump_json()


@pytest.mark.parametrize("code", ["compute_busy", "compute_timeout"])
async def test_http_benchmark_preserves_the_calculation_failure_reason(
    omm_request: CoordinateRequest, code: str
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": {"code": code, "message": "Unavailable", "time": None}})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        sample = await _send(client, omm_request)
    assert sample.status == 503
    assert sample.error_code == code
    assert sample.compute_sec is None
