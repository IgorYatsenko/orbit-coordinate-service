import asyncio
from uuid import uuid4

import httpx
import pytest

from models.pydantic import CoordinateRequest
from models.pydantic.satellites import SatelliteResponse

pytestmark = pytest.mark.integration


async def test_satellite_crud_and_replace_semantics(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/satellites",
        json={
            "norad_id": 25544,
            "name": " ISS (ZARYA) ",
            "international_designator": "1998-067A",
            "launch_date": "1998-11-20",
        },
    )
    assert created.status_code == 201, created.text
    satellite = SatelliteResponse.model_validate_json(created.content)
    assert satellite.name == "ISS (ZARYA)"
    path = f"/api/v1/satellites/{satellite.id}"
    assert (await client.get(path)).json() == created.json()
    replaced = await client.put(path, json={"norad_id": 999999999, "name": "Updated name"})
    assert replaced.status_code == 200, replaced.text
    updated = SatelliteResponse.model_validate_json(replaced.content)
    assert updated.id == satellite.id
    assert updated.norad_id == 999999999
    assert updated.international_designator is None and updated.launch_date is None
    assert updated.created_at == satellite.created_at
    assert updated.updated_at > satellite.updated_at
    removed = await client.delete(path)
    assert removed.status_code == 204 and removed.content == b""
    for method in ("GET", "PUT", "DELETE"):
        missing = await client.request(method, path, json={"norad_id": 25544, "name": "Missing"})
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "satellite_not_found"


async def test_cursor_pages_are_sorted_and_calculation_does_not_register_satellites(
    client: httpx.AsyncClient, omm_request: CoordinateRequest
) -> None:
    for norad_id in (30000, 10000, 20000):
        assert (
            await client.post("/api/v1/satellites", json={"norad_id": norad_id, "name": str(norad_id)})
        ).status_code == 201
    first = (await client.get("/api/v1/satellites?limit=2")).json()
    assert [item["norad_id"] for item in first["items"]] == [10000, 20000]
    assert first["next_after_norad_id"] == 20000
    second = (await client.get("/api/v1/satellites?limit=2&after_norad_id=20000")).json()
    assert [item["norad_id"] for item in second["items"]] == [30000]
    assert second["next_after_norad_id"] is None
    calculated = await client.post("/api/v1/orbits/coordinates", json=omm_request.model_dump(mode="json"))
    assert calculated.status_code == 200
    assert len((await client.get("/api/v1/satellites")).json()["items"]) == 3


async def test_concurrent_duplicate_norad_is_a_conflict_and_update_rolls_back(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(
        *(client.post("/api/v1/satellites", json={"norad_id": 25544, "name": name}) for name in ("First", "Second"))
    )
    assert sorted(item.status_code for item in responses) == [201, 409]
    assert next(item for item in responses if item.status_code == 409).json()["detail"]["code"] == "satellite_conflict"
    other = await client.post("/api/v1/satellites", json={"norad_id": 12345, "name": "Other"})
    path = f"/api/v1/satellites/{other.json()['id']}"
    failed = await client.put(path, json={"norad_id": 25544, "name": "Duplicate"})
    assert failed.status_code == 409
    assert (await client.get(path)).json()["norad_id"] == 12345


@pytest.mark.parametrize(
    "payload",
    [
        {"norad_id": 0, "name": "Invalid"},
        {"norad_id": 25544, "name": "  "},
        {"norad_id": 25544, "name": "ISS", "launch_date": "bad-date"},
    ],
)
async def test_invalid_metadata_does_not_reach_database(
    client: httpx.AsyncClient, payload: dict[str, str | int]
) -> None:
    assert (await client.post("/api/v1/satellites", json=payload)).status_code == 422
    assert (await client.get("/api/v1/satellites")).json()["items"] == []
    assert (await client.get(f"/api/v1/satellites/{uuid4()}")).status_code == 404
