from typing import Literal

from pydantic import BaseModel, ConfigDict


class ServiceInfoResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    database: Literal["ok", "unavailable"]

    model_config = ConfigDict(extra="forbid", frozen=True)
