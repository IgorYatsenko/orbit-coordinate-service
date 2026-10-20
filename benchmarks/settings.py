from pydantic_settings import BaseSettings, SettingsConfigDict

from models.pydantic.benchmarks import BenchmarkConfiguration


class BenchmarkSettings(BaseSettings, BenchmarkConfiguration):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)
