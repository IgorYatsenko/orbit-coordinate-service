from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from models.pydantic.auth import Username


class DevSettings(BaseSettings):
    APP_DEV_USERNAME: Username = Field(default="testuser", description="Local demonstration username.")
    APP_DEV_PASSWORD: SecretStr = Field(
        default=SecretStr("test-password"), min_length=1, max_length=128, description="Local demonstration password."
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True)
