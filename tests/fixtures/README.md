# Sources of numerical test data

`celestrak/iss.json` and `celestrak/iss.tle` are unmodified responses for ISS (NORAD 25544).
`celestrak/sources.json` records URLs, UTC retrieval times and SHA-256 hashes.
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
