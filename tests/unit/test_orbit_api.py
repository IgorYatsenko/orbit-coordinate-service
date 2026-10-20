import json
from unittest.mock import AsyncMock

import httpx
import pytest

from api.dependencies import get_current_user
from api.main import Application
from api.settings import _Settings
from models.exceptions import ComputeBusy, ComputeTimeout, ComputeUnavailable, OrbitCalculationError
from models.pydantic import CalculationResult, CoordinateRequest, RequestValidationErrorResponse


def authorized_application(*, settings: _Settings) -> Application:
    app = Application(settings=settings)
    app.dependency_overrides[get_current_user] = lambda: None
    return app


async def test_point_limit_is_checked_before_submitting_work(
    monkeypatch: pytest.MonkeyPatch, omm_request: CoordinateRequest
) -> None:
    app = authorized_application(settings=_Settings(APP_COMPUTE_MAX_POINTS=60))
    calculate = AsyncMock()
    monkeypatch.setattr(app.services.compute, "calculate", calculate)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/orbits/coordinates", json=omm_request.model_dump(mode="json"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "point_limit_exceeded"
    calculate.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "code", "status_code"),
    [
        (ComputeBusy("Busy"), "compute_busy", 503),
        (ComputeUnavailable("Unavailable"), "compute_unavailable", 503),
        (ComputeTimeout("Timeout"), "compute_timeout", 503),
        (OrbitCalculationError("Invalid orbit"), "invalid_orbit", 422),
    ],
)
async def test_error_response_contract(
    monkeypatch: pytest.MonkeyPatch, omm_request: CoordinateRequest, error: Exception, code: str, status_code: int
) -> None:
    app = authorized_application(settings=_Settings())
    monkeypatch.setattr(app.services.compute, "calculate", AsyncMock(side_effect=error))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/orbits/coordinates", json=omm_request.model_dump(mode="json"))
    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code, "message": str(error), "time": None}}


async def test_worker_json_is_sent_as_json_without_encoding_it_twice(
    monkeypatch: pytest.MonkeyPatch, omm_request: CoordinateRequest
) -> None:
    app = authorized_application(settings=_Settings())
    # Full numerical response validation is covered by real process integration tests.
    result = CalculationResult(payload=b'{"point_count":1}', point_count=1, duration_sec=0.01)
    monkeypatch.setattr(app.services.compute, "calculate", AsyncMock(return_value=result))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/orbits/coordinates", json=omm_request.model_dump(mode="json"))
    assert response.json() == {"point_count": 1}
    assert response.headers["content-type"] == "application/json"


async def test_openapi_documents_both_validation_and_calculation_errors(omm_request: CoordinateRequest) -> None:
    app = authorized_application(settings=_Settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        fields = {**omm_request.model_dump(mode="json"), "step_seconds": 0}
        response = await client.post("/api/v1/orbits/coordinates", json=fields)
        schema = (await client.get("/openapi.json")).json()
    assert response.status_code == 422
    detail = RequestValidationErrorResponse.model_validate(response.json())
    assert detail.detail[0].loc == ["body", "step_seconds"]
    errors = schema["paths"]["/api/v1/orbits/coordinates"]["post"]["responses"]["422"]
    assert len(errors["content"]["application/json"]["schema"]["anyOf"]) == 2


@pytest.mark.parametrize(("name", "fixture_name"), [("tle", "tle_request"), ("omm", "omm_request")])
async def test_openapi_examples_match_documented_requests(
    request: pytest.FixtureRequest, name: str, fixture_name: str
) -> None:
    app = authorized_application(settings=_Settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/openapi.json")).json()
    content = schema["paths"]["/api/v1/orbits/coordinates"]["post"]["requestBody"]["content"]["application/json"]
    sample = CoordinateRequest.model_validate(content["examples"][name]["value"])
    assert sample == request.getfixturevalue(fixture_name)


@pytest.mark.parametrize("value", ["1e999", "-1e999", "NaN", "Infinity"])
async def test_non_finite_input_returns_validation_error(omm_request: CoordinateRequest, value: str) -> None:
    app = authorized_application(settings=_Settings())
    fields = omm_request.model_dump(mode="json")
    fields["orbit"]["elements"]["BSTAR"] = "REPLACE_NUMBER"
    content = json.dumps(fields).replace('"REPLACE_NUMBER"', value)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/orbits/coordinates", content=content, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422
    validation = RequestValidationErrorResponse.model_validate(response.json())
    assert validation.detail[0].loc == ["body", "orbit", "omm", "elements", "BSTAR"]
    assert "input" not in response.json()["detail"][0]


@pytest.mark.parametrize("time", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
@pytest.mark.parametrize("field", ["start", "end", "EPOCH"])
async def test_utc_overflow_returns_a_field_validation_error(
    omm_request: CoordinateRequest, field: str, time: str
) -> None:
    app = authorized_application(settings=_Settings())
    fields = omm_request.model_dump(mode="json")
    if field == "EPOCH":
        fields["orbit"]["elements"][field] = time
    else:
        fields[field] = time
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/orbits/coordinates", json=fields)
    assert response.status_code == 422
    validation = RequestValidationErrorResponse.model_validate(response.json())
    expected = ["body", "orbit", "omm", "elements", field] if field == "EPOCH" else ["body", field]
    assert validation.detail[0].loc == expected
    assert "UTC conversion" in validation.detail[0].msg
