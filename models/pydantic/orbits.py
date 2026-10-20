from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    field_validator,
    model_validator,
)


def _iso_datetime(value: object) -> object:
    if not isinstance(value, (str, datetime)):
        raise ValueError("Use an ISO 8601 datetime string")
    return value


RequestTime = Annotated[AwareDatetime, BeforeValidator(_iso_datetime)]
Angle = Annotated[StrictFloat, Field(ge=0, lt=360)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]


class TLEOrbit(BaseModel):
    format: Literal["tle"]
    name: str | None = Field(default=None, max_length=200)
    line1: str = Field(min_length=69, max_length=69)
    line2: str = Field(min_length=69, max_length=69)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("line1", "line2")
    @classmethod
    def validate_line(cls, value: str) -> str:
        if not value.isascii() or any(not 32 <= ord(character) <= 126 for character in value):
            raise ValueError("TLE lines must contain printable ASCII characters")
        if not value[-1].isdigit():
            raise ValueError("TLE checksum must be a digit")
        checksum = sum(int(character) if character.isdigit() else character == "-" for character in value[:68])
        if checksum % 10 != int(value[-1]):
            raise ValueError("TLE checksum does not match")
        return value

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if not self.line1.startswith("1 ") or not self.line2.startswith("2 "):
            raise ValueError("Expected TLE line 1 followed by line 2")
        if self.line1[2:7] != self.line2[2:7]:
            raise ValueError("TLE catalog numbers must match")
        catalog = self.line1[2:7]
        numeric = catalog.strip().isdigit()
        alpha_five = catalog[0] in "ABCDEFGHJKLMNPQRSTUVWXYZ" and catalog[1:].isdigit()
        if not (numeric or alpha_five):
            raise ValueError("TLE catalog number must be numeric or Alpha-5")
        return self


class GPElements(BaseModel):
    """CelesTrak GP JSON using OMM field names and Earth/TEME/UTC/SGP4 defaults."""

    OBJECT_NAME: str | None = Field(default=None, max_length=200)
    OBJECT_ID: str | None = Field(default=None, max_length=40)
    NORAD_CAT_ID: int = Field(ge=1, le=999_999_999, strict=True)
    EPOCH: Annotated[datetime, BeforeValidator(_iso_datetime)]
    MEAN_MOTION: Annotated[StrictFloat, Field(gt=0)]
    ECCENTRICITY: Annotated[StrictFloat, Field(ge=0, lt=1)]
    INCLINATION: Annotated[StrictFloat, Field(ge=0, le=180)]
    RA_OF_ASC_NODE: Angle
    ARG_OF_PERICENTER: Angle
    MEAN_ANOMALY: Angle
    BSTAR: FiniteFloat
    MEAN_MOTION_DOT: FiniteFloat
    MEAN_MOTION_DDOT: FiniteFloat
    EPHEMERIS_TYPE: Literal[0] = 0
    CLASSIFICATION_TYPE: Literal["U", "C", "S"] = "U"
    ELEMENT_SET_NO: int = Field(default=0, ge=0, strict=True)
    REV_AT_EPOCH: int = Field(default=0, ge=0, strict=True)
    CENTER_NAME: Literal["EARTH"] = "EARTH"
    REF_FRAME: Literal["TEME"] = "TEME"
    TIME_SYSTEM: Literal["UTC"] = "UTC"
    MEAN_ELEMENT_THEORY: Literal["SGP4"] = "SGP4"

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("EPOCH")
    @classmethod
    def epoch_to_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OMMOrbit(BaseModel):
    format: Literal["omm"]
    elements: GPElements

    model_config = ConfigDict(extra="forbid", frozen=True)


class CoordinateRequest(BaseModel):
    orbit: Annotated[TLEOrbit | OMMOrbit, Field(discriminator="format")]
    start: RequestTime
    end: RequestTime
    step_seconds: int = Field(ge=1, le=60, strict=True)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("start", "end")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.start > self.end:
            raise ValueError("start must not be later than end")
        return self

    @property
    def point_count(self) -> int:
        return (self.end - self.start) // timedelta(seconds=self.step_seconds) + 1


class CoordinatePoint(BaseModel):
    time: datetime
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    altitude_km: float = Field(allow_inf_nan=False)

    model_config = ConfigDict(extra="forbid", frozen=True)


class CoordinateResponse(BaseModel):
    norad_id: int
    epoch: datetime
    reference_frame: Literal["WGS84"] = "WGS84"
    start: datetime
    end: datetime
    step_seconds: int
    point_count: int
    points: list[CoordinatePoint]

    model_config = ConfigDict(extra="forbid", frozen=True)


class CalculationErrorDetail(BaseModel):
    code: Literal[
        "invalid_orbit",
        "propagation_failed",
        "point_limit_exceeded",
        "compute_busy",
        "compute_unavailable",
        "compute_timeout",
    ]
    message: str
    time: datetime | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)


class CalculationErrorResponse(BaseModel):
    detail: CalculationErrorDetail

    model_config = ConfigDict(extra="forbid", frozen=True)
