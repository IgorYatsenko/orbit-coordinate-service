from pathlib import Path

import pytest
from pydantic import ValidationError

from api.settings import _Settings, get_settings


def test_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_PORT=8100\nAPP_DB_POOL_SIZE=2\nAPP_TEST_DB_NAME=orbits_test\n")
    monkeypatch.setenv("APP_DB_POOL_SIZE", "7")
    settings = _Settings()
    assert settings.APP_PORT == 8100
    assert settings.APP_DB_POOL_SIZE == 7


def test_database_password_is_escaped_and_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    password = "local:p@ss/word%with?symbols"
    monkeypatch.setenv("APP_DB_PASSWORD", password)
    settings = _Settings()
    assert settings.database_url.password == password
    assert password not in str(settings.database_url)
    assert password not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_DB_POOL_SIZE", "0"),
        ("APP_DB_STATEMENT_TIMEOUT_SEC", "0"),
        ("APP_AUTH_TOKEN_SECRET", "short"),
        ("APP_AUTH_TOKEN_TTL_SEC", "0"),
        ("APP_AUTH_PASSWORD_MEMORY_KIB", "8"),
        ("APP_RATE_LIMIT_USER_REQUESTS", "0"),
        ("APP_REDIS_DB", "16"),
        ("APP_COMPUTE_STALL_TIMEOUT_SEC", "0"),
        ("APP_COMPUTE_STALL_TIMEOUT_SEC", "60"),
        ("APP_COMPUTE_STALL_TIMEOUT_SEC", "Infinity"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[]"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[1,0.1]"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[1,1]"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[0,1]"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[-1,1]"),
        ("APP_METRICS_HTTP_BUCKETS_SEC", "[1,Infinity]"),
    ],
)
def test_invalid_resource_limits_fail_before_startup(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        _Settings()


def test_metrics_configuration_uses_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_METRICS_ENABLED", "false")
    monkeypatch.setenv("APP_METRICS_HTTP_BUCKETS_SEC", "[0.1,1,60]")
    settings = _Settings()
    assert settings.APP_METRICS_ENABLED is False
    assert settings.APP_METRICS_HTTP_BUCKETS_SEC == (0.1, 1.0, 60.0)


def test_config_stays_cached_until_explicit_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "8100")
    initial = get_settings()
    monkeypatch.setenv("APP_PORT", "8200")
    assert get_settings() is initial
    assert get_settings().APP_PORT == 8100
    get_settings.cache_clear()
    assert get_settings().APP_PORT == 8200
