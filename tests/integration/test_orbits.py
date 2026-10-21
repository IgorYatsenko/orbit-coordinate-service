import asyncio
import os
import time
from concurrent.futures.process import BrokenProcessPool

import httpx
import pytest

from api.services.compute import Compute
from models.exceptions import ComputeUnavailable
from models.pydantic import CoordinateRequest, CoordinateResponse

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("fixture_name", ["tle_request", "omm_request"])
async def test_real_process_http_calculation(
    client: httpx.AsyncClient, request: pytest.FixtureRequest, fixture_name: str
) -> None:
    payload: CoordinateRequest = request.getfixturevalue(fixture_name)
    schema = (await client.get("/openapi.json")).json()
    content = schema["paths"]["/api/v1/orbits/coordinates"]["post"]["requestBody"]["content"]["application/json"]
    name = fixture_name.removesuffix("_request")
    example = content["examples"][name]["value"]
    assert CoordinateRequest.model_validate(example) == payload
    response = await client.post("/api/v1/orbits/coordinates", json=example)
    assert response.status_code == 200, response.text
    result = CoordinateResponse.model_validate_json(response.content)
    assert result.norad_id == 25544
    assert result.reference_frame == "WGS84"
    assert result.point_count == 61
    assert result.points[0].time == payload.start
    assert result.points[-1].time == payload.end
    assert result.points[0].latitude_deg == pytest.approx(-0.716162, abs=0.001)
    assert result.points[0].longitude_deg == pytest.approx(-63.077539, abs=0.001)
    assert result.points[0].altitude_km == pytest.approx(419.279, abs=0.01)


async def test_domain_error_crosses_process_boundary(client: httpx.AsyncClient, omm_request: CoordinateRequest) -> None:
    fields = omm_request.model_dump(mode="json")
    fields["orbit"]["elements"]["MEAN_MOTION"] = 20.0
    response = await client.post("/api/v1/orbits/coordinates", json=fields)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "propagation_failed"
    assert detail["time"] == omm_request.start.isoformat().replace("+00:00", "Z")
    assert (await client.get("/health/ready")).status_code == 200


async def test_invalid_tle_motion_returns_422_without_breaking_the_pool(
    client: httpx.AsyncClient, tle_request: CoordinateRequest
) -> None:
    fields = tle_request.model_dump(mode="json")
    line = fields["orbit"]["line2"]
    body = line[:52] + "-1.00000000" + line[63:68]
    checksum = sum(int(character) if character.isdigit() else character == "-" for character in body) % 10
    fields["orbit"]["line2"] = body + str(checksum)
    response = await client.post("/api/v1/orbits/coordinates", json=fields)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_orbit"
    assert (
        await client.post("/api/v1/orbits/coordinates", json=tle_request.model_dump(mode="json"))
    ).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


async def test_actual_worker_crash_is_detected_and_resources_close(omm_request: CoordinateRequest) -> None:
    compute = Compute(
        workers=1,
        chunk_points=64,
        numeric_threads=1,
        timeout_sec=5,
        stall_timeout_sec=10,
        start_timeout_sec=15,
        healthcheck_timeout_sec=1,
    )
    try:
        await compute.start()
        assert await compute.ping() is True
        # Exercise an actual process death, not a mocked executor state.
        with pytest.raises(BrokenProcessPool):
            await asyncio.shield(compute._submit(False, os._exit, 17))
        assert await compute.ping() is False
        with pytest.raises(ComputeUnavailable):
            await compute.calculate(omm_request)
    finally:
        await compute.stop()


async def test_overdue_real_process_finishes_and_the_pool_recovers(
    omm_request: CoordinateRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    compute = Compute(
        workers=2,
        chunk_points=64,
        numeric_threads=1,
        timeout_sec=5,
        stall_timeout_sec=10,
        start_timeout_sec=15,
        healthcheck_timeout_sec=5,
    )
    try:
        await compute.start()
        # A bounded slow job demonstrates detection without killing or cancelling the process.
        monkeypatch.setattr("api.services.compute.monotonic", lambda: 0.0)
        future = compute._submit(True, time.sleep, 0.5)
        monkeypatch.setattr("api.services.compute.monotonic", lambda: 11.0)
        assert await compute.ping() is False
        with pytest.raises(ComputeUnavailable, match="overdue"):
            await compute.calculate(omm_request)
        await asyncio.wait_for(asyncio.shield(future), timeout=10)
        assert not future.cancelled()
        assert await compute.ping() is True
        assert (await compute.calculate(omm_request)).point_count == omm_request.point_count
    finally:
        await compute.stop()
