from typing import Literal

from pydantic import BaseModel, ConfigDict


class ServiceInfoResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str

    model_config = ConfigDict(extra="forbid", frozen=True)
