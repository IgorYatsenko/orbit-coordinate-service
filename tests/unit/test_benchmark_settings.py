from pathlib import Path

import pytest

from benchmarks.settings import BenchmarkSettings
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
