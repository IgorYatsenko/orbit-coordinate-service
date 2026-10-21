from uuid import uuid4

import httpx
from prometheus_client.parser import text_string_to_metric_families

from api.main import Application
from api.settings import _Settings


def sample_value(payload: str, name: str, labels: dict[str, str]) -> float:
    return next(
        sample.value
        for family in text_string_to_metric_families(payload)
        for sample in family.samples
        if sample.name == name and sample.labels == labels
    )


async def test_metrics_group_route_parameters_and_unknown_paths_without_exposing_inputs() -> None:
    app = Application(settings=_Settings(APP_METRICS_HTTP_BUCKETS_SEC=(0.01, 1.0)))
    identities = [str(uuid4()), str(uuid4())]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for identity in identities:
            assert (await client.put(f"/api/v1/satellites/{identity}?secret=hidden-input", json={})).status_code == 401
            assert (await client.get(f"/unknown/{identity}")).status_code == 404
        assert (await client.request("CUSTOM-METHOD", "/unknown/another-value")).status_code == 404
        assert (await client.get("/health/live")).status_code == 200
        response = await client.get("/metrics")
        repeated = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert repeated.text == response.text
    labels = {"method": "PUT", "route": "/api/v1/satellites/{satellite_id}", "status": "401"}
    assert sample_value(response.text, "orbit_http_requests_total", labels) == 2
    assert sample_value(response.text, "orbit_http_request_duration_seconds_count", labels) == 2
    assert sample_value(response.text, "orbit_http_request_duration_seconds_sum", labels) > 0
    assert sample_value(response.text, "orbit_http_request_duration_seconds_bucket", {**labels, "le": "+Inf"}) == 2
    assert (
        sample_value(
            response.text, "orbit_http_requests_total", {"method": "GET", "route": "unmatched", "status": "404"}
        )
        == 2
    )
    assert (
        sample_value(
            response.text, "orbit_http_requests_total", {"method": "OTHER", "route": "unmatched", "status": "404"}
        )
        == 1
    )
    for hidden in (*identities, "hidden-input", "CUSTOM-METHOD", "/unknown/", "/metrics", "/health/live"):
        assert hidden not in response.text


async def test_unhandled_failure_is_recorded_once_as_500() -> None:
    app = Application(settings=_Settings())

    async def fail() -> None:
        raise RuntimeError("internal failure details")

    app.add_api_route("/failure", fail)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/failure")).status_code == 500
        response = await client.get("/metrics")
    assert (
        sample_value(
            response.text, "orbit_http_requests_total", {"method": "GET", "route": "/failure", "status": "500"}
        )
        == 1
    )
    assert "internal failure details" not in response.text


async def test_metrics_belong_to_an_application_instance() -> None:
    for previous_requests in (1, 0):
        app = Application(settings=_Settings())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(previous_requests):
                await client.get("/unknown")
            response = await client.get("/metrics")
        samples = [
            sample.value
            for family in text_string_to_metric_families(response.text)
            for sample in family.samples
            if sample.name == "orbit_http_requests_total"
        ]
        assert sum(samples) == previous_requests


async def test_metrics_can_be_disabled() -> None:
    app = Application(settings=_Settings(APP_METRICS_ENABLED=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/metrics")).status_code == 404
        assert (await client.get("/health/live")).status_code == 200
