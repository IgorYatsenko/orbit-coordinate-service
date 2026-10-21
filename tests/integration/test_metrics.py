import asyncio
import json
import os
import signal
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from api.main import Application
from api.settings import _Settings

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def test_metrics_remain_public_after_user_quota_is_exhausted(
    application: Application, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = application.services.config.model_copy(update={"APP_RATE_LIMIT_USER_REQUESTS": 1})
    monkeypatch.setattr(application.services, "config", config)
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 429
    assert (await client.get("/health/ready")).status_code == 200
    client.headers.clear()
    rejected = await client.post("/api/v1/auth/login", json={"username": "unknown", "password": "wrong"})
    assert rejected.status_code == 401
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    for route, status in (("/api/v1/auth/me", "200"), ("/api/v1/auth/me", "429")):
        assert f'orbit_http_requests_total{{method="GET",route="{route}",status="{status}"}} 1.0' in metrics.text
    assert 'orbit_http_requests_total{method="POST",route="/api/v1/auth/login",status="401"} 1.0' in metrics.text
    for hidden in ("/health/ready", "reviewer", "unknown", "wrong", "access_token"):
        assert hidden not in metrics.text


@pytest.mark.parametrize("http_workers", [1, 2])
async def test_server_aggregates_worker_metrics_and_removes_files_on_shutdown(
    app_settings: _Settings, migrated_database: None, http_workers: int
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "APP_HTTP_WORKERS": str(http_workers),
        "APP_LOG_LEVEL": "WARNING",
        "APP_DB_HOST": app_settings.APP_DB_HOST,
        "APP_DB_PORT": str(app_settings.APP_DB_PORT),
        "APP_DB_USER": app_settings.APP_DB_USER,
        "APP_DB_PASSWORD": app_settings.APP_DB_PASSWORD.get_secret_value(),
        "APP_DB_NAME": app_settings.APP_DB_NAME,
        "APP_REDIS_HOST": app_settings.APP_REDIS_HOST,
        "APP_REDIS_PORT": str(app_settings.APP_REDIS_PORT),
        "APP_REDIS_PASSWORD": app_settings.APP_REDIS_PASSWORD.get_secret_value(),
        "APP_REDIS_DB": "15",
        "APP_REDIS_KEY_PREFIX": app_settings.APP_REDIS_KEY_PREFIX,
        "APP_AUTH_TOKEN_SECRET": app_settings.APP_AUTH_TOKEN_SECRET.get_secret_value(),
        "APP_AUTH_PASSWORD_MEMORY_KIB": "1024",
        "APP_AUTH_PASSWORD_TIME_COST": "1",
        "APP_AUTH_PASSWORD_PARALLELISM": "1",
        "APP_COMPUTE_WORKERS": "1",
        "APP_METRICS_ENABLED": "true",
        "APP_METRICS_HTTP_BUCKETS_SEC": json.dumps([0.01, 1, 60]),
    }
    # A short path also fits macOS's limit for multiprocessing Unix-domain socket names.
    with TemporaryDirectory(prefix="orbit-metrics-test-", dir="/tmp") as temporary:
        environment["TMPDIR"] = temporary
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "api",
            cwd=PROJECT_ROOT,
            env=environment,
            start_new_session=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", limits=httpx.Limits(max_keepalive_connections=0), timeout=2
            ) as client:
                async with asyncio.timeout(45):
                    while True:
                        if process.returncode is not None:
                            output, _ = await process.communicate()
                            pytest.fail(f"HTTP server exited early: {output.decode()[-1500:]}")
                        try:
                            ready = await client.get("/health/ready")
                            if ready.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.05)
                    requests = 0
                    while True:
                        responses = await asyncio.gather(*(client.get("/api/v1/satellites") for _ in range(8)))
                        assert all(response.status_code == 401 for response in responses)
                        requests += len(responses)
                        files = await asyncio.to_thread(
                            lambda: list(Path(temporary).glob("orbit-metrics-*/counter_*.db"))
                        )
                        if len(files) == (http_workers if http_workers > 1 else 0):
                            break
                        await asyncio.sleep(0.05)
                response = await client.get("/metrics")
                assert response.status_code == 200
                label = '{method="GET",route="/api/v1/satellites",status="401"}'
                assert f"orbit_http_requests_total{label} {float(requests)}" in response.text
                assert f"orbit_http_request_duration_seconds_count{label} {float(requests)}" in response.text
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.communicate(), timeout=15)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.communicate()
        assert process.returncode in (0, -signal.SIGTERM)
        assert not await asyncio.to_thread(lambda: list(Path(temporary).glob("orbit-metrics-*")))
