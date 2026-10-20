import calendar
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
from sgp4.earth_gravity import wgs72
from sgp4.io import twoline2rv
from skyfield.api import EarthSatellite, load, wgs84
from skyfield.timelib import Timescale

from models.exceptions import OrbitCalculationError
from models.pydantic import CoordinatePoint, CoordinateRequest, CoordinateResponse, OMMOrbit, TLEOrbit


class OrbitCalculator:
    """Own the bundled timescale and vectorization configuration of one calculator."""

    def __init__(self, *, chunk_points: int) -> None:
        self._chunk_points = chunk_points
        self._timescale: Timescale = load.timescale(builtin=True)

    @staticmethod
    def _validate_tle(orbit: TLEOrbit) -> None:
        try:
            parsed = twoline2rv(orbit.line1, orbit.line2, wgs72)
            epoch_year = int(orbit.line1[18:20])
            epoch_year += 2000 if epoch_year < 57 else 1900
            values = (
                parsed.inclo,
                parsed.nodeo,
                parsed.ecco,
                parsed.argpo,
                parsed.mo,
                parsed.no_kozai,
                parsed.bstar,
                parsed.ndot,
                parsed.nddot,
            )
            valid = (
                all(math.isfinite(value) for value in values)
                and 0 <= parsed.inclo <= math.pi
                and 0 <= parsed.nodeo < 2 * math.pi
                and 0 <= parsed.argpo < 2 * math.pi
                and 0 <= parsed.mo < 2 * math.pi
                and 0 <= parsed.ecco < 1
                and parsed.no_kozai > 0
                and 1 <= parsed.epochdays < 366 + calendar.isleap(epoch_year)
                and parsed.satnum > 0
            )
            if not valid:
                raise ValueError("Orbital elements are outside their supported ranges")
        except (ValueError, OverflowError, ZeroDivisionError) as error:
            raise OrbitCalculationError(f"Invalid TLE: {error}") from error

    def build_satellite(self, orbit: TLEOrbit | OMMOrbit) -> EarthSatellite:
        timescale = self._timescale
        if isinstance(orbit, TLEOrbit):
            self._validate_tle(orbit)
            # Skyfield's TLE constructor uses SGP4's standard WGS72 gravity constants.
            return EarthSatellite(orbit.line1, orbit.line2, orbit.name, timescale)

        # Adapt the typed contract to the external library's dictionary interface.
        fields = orbit.elements.model_dump(mode="json")
        fields["OBJECT_ID"] = orbit.elements.OBJECT_ID or ""
        fields["EPOCH"] = orbit.elements.EPOCH.replace(tzinfo=None).isoformat(timespec="microseconds")
        # sgp4 2.27 limits its identifier label to Alpha-5. It is not a dynamical input.
        # Keep the real, up-to-nine-digit catalog number in our typed contract and response.
        if orbit.elements.NORAD_CAT_ID > 339_999:
            fields["NORAD_CAT_ID"] = 0
        try:
            return EarthSatellite.from_omm(timescale, fields)
        except (ValueError, OverflowError, ZeroDivisionError) as error:
            raise OrbitCalculationError(f"Invalid OMM: {error}") from error

    @staticmethod
    def _source_epoch(orbit: TLEOrbit | OMMOrbit) -> datetime:
        if isinstance(orbit, OMMOrbit):
            return orbit.elements.EPOCH
        year = int(orbit.line1[18:20])
        year += 2000 if year < 57 else 1900
        microseconds = int((Decimal(orbit.line1[20:32]) - 1) * 86_400_000_000)
        return datetime(year, 1, 1, tzinfo=UTC) + timedelta(microseconds=microseconds)

    def calculate(self, request: CoordinateRequest) -> CoordinateResponse:
        satellite = self.build_satellite(request.orbit)
        points: list[CoordinatePoint] = []
        step = timedelta(seconds=request.step_seconds)
        timescale = self._timescale

        for offset in range(0, request.point_count, self._chunk_points):
            dates = [
                request.start + index * step
                for index in range(offset, min(offset + self._chunk_points, request.point_count))
            ]
            position = satellite.at(timescale.from_datetimes(dates))
            for date, message in zip(dates, position.message, strict=True):
                if message is not None:
                    raise OrbitCalculationError(f"SGP4: {message}", date)

            geographic = wgs84.geographic_position_of(position)
            coordinates = np.column_stack(
                (geographic.latitude.degrees, geographic.longitude.degrees, geographic.elevation.km)
            )
            finite = np.isfinite(coordinates).all(axis=1)
            if not finite.all():
                index = int(np.flatnonzero(~finite)[0])
                raise OrbitCalculationError("Coordinate transformation returned a non-finite value", dates[index])

            points.extend(
                CoordinatePoint(time=date, latitude_deg=float(lat), longitude_deg=float(lon), altitude_km=float(alt))
                for date, (lat, lon, alt) in zip(dates, coordinates, strict=True)
            )

        return CoordinateResponse(
            norad_id=request.orbit.elements.NORAD_CAT_ID
            if isinstance(request.orbit, OMMOrbit)
            else satellite.model.satnum,
            epoch=self._source_epoch(request.orbit),
            start=request.start,
            end=request.end,
            step_seconds=request.step_seconds,
            point_count=len(points),
            points=points,
        )
