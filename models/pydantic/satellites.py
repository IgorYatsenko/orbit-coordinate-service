from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class SatelliteWrite(BaseModel):
    norad_id: int = Field(ge=1, le=999999999, strict=True, examples=[25544])
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        examples=["ISS (ZARYA)"]
    )
    international_designator: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] | None
    ) = Field(default=None, examples=["1998-067A"])
    launch_date: date | None = Field(default=None, examples=["1998-11-20"])

    model_config = ConfigDict(extra="forbid", frozen=True)


class SatelliteResponse(SatelliteWrite):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class SatellitePage(BaseModel):
    items: list[SatelliteResponse]
    next_after_norad_id: int | None

    model_config = ConfigDict(extra="forbid", frozen=True)
