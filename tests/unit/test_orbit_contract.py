from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from models.pydantic import CoordinateRequest, GPElements, TLEOrbit


@pytest.mark.parametrize("step", [0, 61, 1.5, True, "1"])
def test_step_must_be_an_integer_from_one_to_sixty(omm_request: CoordinateRequest, step: object) -> None:
    with pytest.raises(ValidationError):
        CoordinateRequest.model_validate({**omm_request.model_dump(), "step_seconds": step})


@pytest.mark.parametrize("time", ["2026-10-20T05:01:00", 1_792_472_460, "2026-10-20"])
def test_interval_requires_explicit_timezone(omm_request: CoordinateRequest, time: object) -> None:
    with pytest.raises(ValidationError):
        CoordinateRequest.model_validate({**omm_request.model_dump(), "start": time})


def test_offset_normalization_and_exact_grid(omm_request: CoordinateRequest) -> None:
    request = CoordinateRequest.model_validate(
        {
            **omm_request.model_dump(),
            "start": "2026-10-20T08:01:00.000001+03:00",
            "end": "2026-10-20T05:02:00Z",
            "step_seconds": 60,
        }
    )
    assert request.start == datetime(2026, 10, 20, 5, 1, 0, 1, tzinfo=UTC)
    assert request.point_count == 1
    equal = CoordinateRequest.model_validate({**request.model_dump(), "end": request.start})
    assert equal.point_count == 1
    day = CoordinateRequest.model_validate(
        {**request.model_dump(), "end": request.start + timedelta(days=1), "step_seconds": 1}
    )
    assert day.point_count == 86_401


def test_reversed_interval_and_unknown_fields_are_rejected(omm_request: CoordinateRequest) -> None:
    for change in ({"start": omm_request.end + timedelta(seconds=1)}, {"extra": "unknown"}):
        with pytest.raises(ValidationError):
            CoordinateRequest.model_validate({**omm_request.model_dump(), **change})


@pytest.mark.parametrize(
    "change",
    [
        {"NORAD_CAT_ID": True},
        {"NORAD_CAT_ID": 1_000_000_000},
        {"ECCENTRICITY": 1.0},
        {"MEAN_MOTION": 0.0},
        {"INCLINATION": 181.0},
        {"RA_OF_ASC_NODE": 360.0},
        {"BSTAR": float("nan")},
        {"MEAN_MOTION_DOT": float("inf")},
        {"REF_FRAME": "GCRF"},
        {"TIME_SYSTEM": "TAI"},
        {"MEAN_ELEMENT_THEORY": "KEPLER"},
    ],
)
def test_gp_fields_have_explicit_semantics(omm_request: CoordinateRequest, change: dict[str, object]) -> None:
    fields = omm_request.orbit.model_dump()["elements"]
    with pytest.raises(ValidationError):
        GPElements.model_validate({**fields, **change})


def test_tle_checksum_is_verified(tle_request: CoordinateRequest) -> None:
    fields = tle_request.orbit.model_dump()
    fields["line1"] = fields["line1"][:-1] + str((int(fields["line1"][-1]) + 1) % 10)
    with pytest.raises(ValidationError, match="checksum"):
        TLEOrbit.model_validate(fields)
