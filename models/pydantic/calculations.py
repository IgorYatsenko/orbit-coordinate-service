from pydantic import BaseModel, ConfigDict, Field


class CalculationResult(BaseModel):
    """Serialized trajectory and metrics transferred from a calculation process."""

    payload: bytes = Field(strict=True)
    point_count: int = Field(ge=1, strict=True)
    duration_sec: float = Field(ge=0, allow_inf_nan=False)
    peak_rss_bytes: int = Field(default=0, ge=0, strict=True)

    model_config = ConfigDict(extra="forbid", frozen=True)
