from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class BenchmarkConfiguration(BaseModel):
    APP_BENCH_USERNAME: str = Field(default="", exclude=True, description="Account used for HTTP measurements.")
    APP_BENCH_PASSWORD: SecretStr = Field(
        default=SecretStr(""), exclude=True, description="Benchmark account password; never included in reports."
    )
    APP_BENCH_MODE: Literal["core", "http"] = Field(default="http", description="Direct worker or HTTP measurement.")
    APP_BENCH_BASE_URL: str = Field(default="http://127.0.0.1:8000", description="Running API URL.")
    APP_BENCH_INPUT: Path = Field(default=Path("examples/request-omm.json"), description="Fixed input request file.")
    APP_BENCH_OUTPUT: Path = Field(
        default=Path("artifacts/benchmark.json"), description="Machine-readable report file."
    )
    APP_BENCH_REPETITIONS: int = Field(default=5, ge=1, description="Sequential repetitions per scenario.")
    APP_BENCH_CONCURRENCY: int = Field(default=4, ge=1, description="Simultaneous requests at the point limit.")
    APP_BENCH_TIMEOUT_SEC: float = Field(default=90, gt=0, description="Client timeout per HTTP operation.")
    APP_BENCH_HEALTH_INTERVAL_SEC: float = Field(
        default=0.05, gt=0, description="Delay between pairs of health probes."
    )


class BenchmarkSample(BaseModel):
    status: int | None
    elapsed_sec: float
    compute_sec: float | None
    response_bytes: int
    worker_peak_rss_bytes: int | None = None
    error_code: str | None = None


class BenchmarkScenario(BaseModel):
    name: str
    point_count: int
    samples: list[BenchmarkSample]


class BenchmarkHealthSample(BaseModel):
    path: str
    status: int | None
    elapsed_sec: float
    error_code: str | None = None


class BenchmarkReport(BaseModel):
    recorded_at: datetime
    mode: str
    python: str
    platform: str
    cpu_count: int | None
    dependencies: dict[str, str]
    input_sha256: str
    compute_settings: dict[str, int | float]
    benchmark_settings: BenchmarkConfiguration
    scenarios: list[BenchmarkScenario]
    health: list[BenchmarkHealthSample]
    completed: bool = False
    failure: str | None = None
