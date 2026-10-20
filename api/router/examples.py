from fastapi.openapi.models import Example

from models.pydantic import CoordinateRequest

_tle_request = CoordinateRequest.model_validate(
    {
        "orbit": {
            "format": "tle",
            "name": "ISS (ZARYA)",
            "line1": "1 25544U 98067A   26293.20919040  .00007447  00000+0  14339-3 0  9991",
            "line2": "2 25544  51.6325  41.4118 0006741 286.2755  73.7491 15.48951472591132",
        },
        "start": "2026-10-20T05:01:00+00:00",
        "end": "2026-10-20T06:01:00+00:00",
        "step_seconds": 60,
    }
)

_omm_request = CoordinateRequest.model_validate(
    {
        "orbit": {
            "format": "omm",
            "elements": {
                "OBJECT_NAME": "ISS (ZARYA)",
                "OBJECT_ID": "1998-067A",
                "EPOCH": "2026-10-20T05:01:14.050560",
                "MEAN_MOTION": 15.48951472,
                "ECCENTRICITY": 0.00067415,
                "INCLINATION": 51.6325,
                "RA_OF_ASC_NODE": 41.4118,
                "ARG_OF_PERICENTER": 286.2755,
                "MEAN_ANOMALY": 73.7491,
                "EPHEMERIS_TYPE": 0,
                "CLASSIFICATION_TYPE": "U",
                "NORAD_CAT_ID": 25544,
                "ELEMENT_SET_NO": 999,
                "REV_AT_EPOCH": 59113,
                "BSTAR": 0.00014339338,
                "MEAN_MOTION_DOT": 7.447e-05,
                "MEAN_MOTION_DDOT": 0,
            },
        },
        "start": "2026-10-20T05:01:00+00:00",
        "end": "2026-10-20T06:01:00+00:00",
        "step_seconds": 60,
    }
)

COORDINATE_EXAMPLES: dict[str, Example] = {
    "tle": Example(
        summary="ISS: two TLE lines",
        description="Captured CelesTrak elements, epoch 2026-10-20T05:01:14.050560Z. One hour, 61 points.",
        value=_tle_request.model_dump(mode="json"),
    ),
    "omm": Example(
        summary="ISS: CelesTrak GP JSON (OMM fields)",
        description="The same orbit in JSON. All times are UTC; one hour, 61 points.",
        value=_omm_request.model_dump(mode="json"),
    ),
}
