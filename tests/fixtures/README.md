# Sources of numerical test data

`celestrak/iss.json` and `celestrak/iss.tle` are unmodified responses for ISS (NORAD 25544).
`celestrak/sources.json` records URLs, UTC retrieval times and SHA-256 hashes.
Git attributes and pre-commit exclusions preserve their original bytes, including CRLF.
The source-manifest test also runs after checkout in CI.
The request files under `examples/` wrap those elements in the API contract.
Their epoch is 2026-10-20T05:01:14.050560Z. JSON retains slightly more precision than TLE.
Tests use a 0.0001 degree / 0.001 km agreement tolerance for these two representations.
This measures format conversion agreement, not the physical accuracy of the orbit prediction.

The TEME position and velocity values in `test_orbit_core.py` are selected numerical
records for satellite 00005 from Vallado's SGP4 verification data:

- [Reference TLE](https://github.com/brandon-rhodes/python-sgp4/blob/master/sgp4/SGP4-VER.TLE)
- [Reference vectors](https://github.com/brandon-rhodes/python-sgp4/blob/master/sgp4/tcppver.out)
- [Original paper and reference implementation](https://celestrak.org/publications/AIAA/2006-6753/)

Position tolerance is 1e-7 km and velocity tolerance is 1e-9 km/s; those values cover
the rounding of the published vectors. WGS84 conversion is checked separately using
the forward ellipsoid formula against Earth-fixed Cartesian coordinates.
The tests never fetch remote data.

## Independent WGS84 reference

`test_wgs84_matches_independent_astropy_reference` checks the complete TLE-to-WGS84
calculation against four frozen reference points generated on 2026-10-21.
The inputs are the published TEME position vectors above: satellite 00005 at
0, 360 and 1440 minutes, and satellite 04632 at -5184 minutes from its epoch.
UTC epochs are `2000-06-27T18:50:19.733568` and `2004-01-31T21:51:25.308576`.
Add the corresponding minute offset without rounding the fractional seconds.

The independent conversion follows [Astropy's satellite guide](https://docs.astropy.org/en/stable/coordinates/satellites.html):

```python
from astropy import units as u
from astropy.coordinates import TEME, ITRS, CartesianRepresentation
from astropy.time import Time
from astropy.utils import iers

iers.conf.auto_download = False
with iers.earth_orientation_table.set(iers.IERS_B.open(iers.IERS_B_FILE)):
    time = Time(utc_time, scale="utc")
    teme = TEME(CartesianRepresentation(position_km * u.km), obstime=time)
    location = teme.transform_to(ITRS(obstime=time)).earth_location
    longitude, latitude, height = location.to_geodetic("WGS84")
```

Generation used Astropy 8.0.1, pyerfa 2.0.1.5, NumPy 2.5.4 and
astropy-iers-data 0.2026.10.19.0.52.1. The bundled IERS-B file SHA-256 is
`6fc2c9d9a7cd7e9a1f597866545bb75baab292f5d51ca9358d5c64c0ce2fa64f`.
The suite uses the frozen numbers and requires only the project's locked dependencies.

Angular tolerance is 0.0001 degrees, allowing the different Earth-orientation
models, including polar motion in Astropy. Height tolerance is 0.0001 km (0.1 m).
These tolerances check implementation agreement; they do not estimate the physical
accuracy of a real satellite prediction.
