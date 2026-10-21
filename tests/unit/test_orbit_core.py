import math
from datetime import datetime, timedelta
from unittest.mock import Mock

import numpy as np
import pytest
from skyfield.framelib import itrs

from api.orbits.core import OrbitCalculator
from models.exceptions import OrbitCalculationError
from models.pydantic import CoordinateRequest, OMMOrbit, TLEOrbit


@pytest.mark.parametrize(
    ("minutes", "expected_position", "expected_velocity"),
    [
        (0, (7022.46529266, -1400.08296755, 0.03995155), (1.893841015, 6.405893759, 4.534807250)),
        (360, (-7154.03120202, -3783.17682504, -3536.19412294), (4.741887409, -4.151817765, -2.093935425)),
        (1440, (-938.55923943, -6268.18748831, -4294.02924751), (7.536105209, -0.427127707, 0.989878080)),
    ],
)
def test_vallado_teme_reference_vectors(
    minutes: int, expected_position: tuple[float, ...], expected_velocity: tuple[float, ...]
) -> None:
    # Numerical data from Vallado's verification case 00005 (see fixtures/README.md).
    orbit = TLEOrbit(
        format="tle",
        line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
        line2="2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667",
    )
    satellite = OrbitCalculator(chunk_points=64).build_satellite(orbit)
    error, position, velocity = satellite.model.sgp4_tsince(minutes)
    assert error == 0
    np.testing.assert_allclose(position, expected_position, rtol=0, atol=1e-7)
    np.testing.assert_allclose(velocity, expected_velocity, rtol=0, atol=1e-9)


def test_celestrak_tle_and_json_agree_with_rounding_tolerance(
    tle_request: CoordinateRequest, omm_request: CoordinateRequest
) -> None:
    tle = OrbitCalculator(chunk_points=17).calculate(tle_request)
    omm = OrbitCalculator(chunk_points=64).calculate(omm_request)
    assert tle.epoch == omm.epoch
    assert tle.point_count == omm.point_count == 61
    for first, second in zip(tle.points, omm.points, strict=True):
        assert first.time == second.time
        assert first.latitude_deg == pytest.approx(second.latitude_deg, abs=1e-4)
        assert first.longitude_deg == pytest.approx(second.longitude_deg, abs=1e-4)
        assert first.altitude_km == pytest.approx(second.altitude_km, abs=0.001)


def test_deep_space_reference_before_epoch() -> None:
    orbit = TLEOrbit(
        format="tle",
        line1="1 04632U 70093B   04031.91070959 -.00000084  00000-0  10000-3 0  9955",
        line2="2 04632  11.4628 273.1101 1450506 207.6000 143.9350  1.20231981 44145",
    )
    satellite = OrbitCalculator(chunk_points=64).build_satellite(orbit)
    error, position, velocity = satellite.model.sgp4_tsince(-5184)
    assert error == 0
    np.testing.assert_allclose(position, (-29020.02587128, 13819.84419063, -5713.33679183), rtol=0, atol=1e-7)
    np.testing.assert_allclose(velocity, (-1.768068390, -3.235371192, -0.395206135), rtol=0, atol=1e-9)


def test_wgs84_output_reconstructs_the_earth_fixed_position(omm_request: CoordinateRequest) -> None:
    response = OrbitCalculator(chunk_points=16).calculate(omm_request)
    satellite = OrbitCalculator(chunk_points=64).build_satellite(omm_request.orbit)
    for point in response.points[::15]:
        time = satellite.epoch.ts.from_datetime(point.time)
        expected = satellite.at(time).frame_xyz(itrs).km
        # Independent forward ellipsoid formula, including the km/metre boundary.
        a = 6378.137
        eccentricity_squared = (1 / 298.257223563) * (2 - 1 / 298.257223563)
        lat, lon = math.radians(point.latitude_deg), math.radians(point.longitude_deg)
        radius = a / math.sqrt(1 - eccentricity_squared * math.sin(lat) ** 2)
        reconstructed = (
            (radius + point.altitude_km) * math.cos(lat) * math.cos(lon),
            (radius + point.altitude_km) * math.cos(lat) * math.sin(lon),
            (radius * (1 - eccentricity_squared) + point.altitude_km) * math.sin(lat),
        )
        np.testing.assert_allclose(reconstructed, expected, rtol=0, atol=1e-6)
        assert 300 < point.altitude_km < 600


@pytest.mark.parametrize(
    ("catalog", "time", "expected"),
    [
        ("00005", "2000-06-27T18:50:19.733568+00:00", (0.000387869157, 149.954879429419, 782.536928077440)),
        ("00005", "2000-06-28T00:50:19.733568+00:00", (-23.705429777608, -81.145540031150, 2456.906224292155)),
        ("00005", "2000-06-28T18:50:19.733568+00:00", (-34.266374746649, 61.728762002019, 1284.309485741450)),
        ("04632", "2004-01-28T07:27:25.308576+00:00", (-10.091999716854, -84.235694739948, 26268.990923563153)),
    ],
)
def test_wgs84_matches_independent_astropy_reference(
    catalog: str, time: str, expected: tuple[float, float, float]
) -> None:
    # Astropy converted published Vallado TEME vectors; see fixtures/README.md.
    orbits = {
        "00005": TLEOrbit(
            format="tle",
            line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
            line2="2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667",
        ),
        "04632": TLEOrbit(
            format="tle",
            line1="1 04632U 70093B   04031.91070959 -.00000084  00000-0  10000-3 0  9955",
            line2="2 04632  11.4628 273.1101 1450506 207.6000 143.9350  1.20231981 44145",
        ),
    }
    date = datetime.fromisoformat(time)
    request = CoordinateRequest(orbit=orbits[catalog], start=date, end=date, step_seconds=1)
    point = OrbitCalculator(chunk_points=16).calculate(request).points[0]
    assert point.time == date
    # Angular tolerance includes the libraries' different Earth-orientation models.
    assert point.latitude_deg == pytest.approx(expected[0], rel=0, abs=1e-4)
    assert point.longitude_deg == pytest.approx(expected[1], rel=0, abs=1e-4)
    assert point.altitude_km == pytest.approx(expected[2], rel=0, abs=1e-4)


def test_calculation_supports_past_future_and_single_point(omm_request: CoordinateRequest) -> None:
    orbit = omm_request.orbit
    assert isinstance(orbit, OMMOrbit)
    for offset in (-1, 0, 1):
        time = orbit.elements.EPOCH + timedelta(days=offset)
        request = CoordinateRequest.model_validate({**omm_request.model_dump(), "start": time, "end": time})
        response = OrbitCalculator(chunk_points=4096).calculate(request)
        assert response.point_count == 1
        assert response.points[0].time == time


def test_large_json_catalog_number_preserves_identity_and_coordinates(omm_request: CoordinateRequest) -> None:
    fields = omm_request.model_dump()
    fields["orbit"]["elements"]["NORAD_CAT_ID"] = 999_999_999
    large = CoordinateRequest.model_validate(fields)
    expected = OrbitCalculator(chunk_points=64).calculate(omm_request)
    response = OrbitCalculator(chunk_points=64).calculate(large)
    assert response.norad_id == 999_999_999
    assert response.points == expected.points


def test_decayed_orbit_fails_whole_calculation_with_time(omm_request: CoordinateRequest) -> None:
    fields = omm_request.model_dump()
    fields["orbit"]["elements"]["MEAN_MOTION"] = 20.0
    request = CoordinateRequest.model_validate(fields)
    with pytest.raises(OrbitCalculationError, match="SGP4") as caught:
        OrbitCalculator(chunk_points=64).calculate(request)
    assert caught.value.time == request.start


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_transformed_point_rejects_the_whole_result(
    monkeypatch: pytest.MonkeyPatch, omm_request: CoordinateRequest, value: float
) -> None:
    geographic = Mock()
    geographic.latitude.degrees = np.zeros(omm_request.point_count)
    geographic.longitude.degrees = np.zeros(omm_request.point_count)
    geographic.elevation.km = np.full(omm_request.point_count, 400.0)
    geographic.elevation.km[2] = value
    monkeypatch.setattr("api.orbits.core.wgs84.geographic_position_of", lambda _: geographic)
    with pytest.raises(OrbitCalculationError, match="non-finite") as caught:
        OrbitCalculator(chunk_points=64).calculate(omm_request)
    assert caught.value.time == omm_request.start + timedelta(seconds=2 * omm_request.step_seconds)


def test_non_leap_tle_epoch_cannot_roll_into_next_year(tle_request: CoordinateRequest) -> None:
    fields = tle_request.orbit.model_dump()
    body = fields["line1"][:18] + "27366.25000000" + fields["line1"][32:68]
    checksum = sum(int(character) if character.isdigit() else character == "-" for character in body) % 10
    fields["line1"] = body + str(checksum)
    orbit = TLEOrbit.model_validate(fields)
    with pytest.raises(OrbitCalculationError, match="outside their supported ranges"):
        OrbitCalculator(chunk_points=64).build_satellite(orbit)
