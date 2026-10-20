import pytest

from dev.settings import DevSettings


def test_demo_credentials_have_defaults_and_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = DevSettings()
    assert defaults.APP_DEV_USERNAME == "testuser"
    assert defaults.APP_DEV_PASSWORD.get_secret_value() == "test-password"
    monkeypatch.setenv("APP_DEV_USERNAME", " Another-User ")
    monkeypatch.setenv("APP_DEV_PASSWORD", "a-different-demo-password")
    settings = DevSettings()
    assert settings.APP_DEV_USERNAME == "another-user"
    assert settings.APP_DEV_PASSWORD.get_secret_value() == "a-different-demo-password"
    assert "a-different-demo-password" not in repr(settings)
