from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import Request, Response

from api.main import Application
from api.settings import _Settings


@pytest.fixture
def application() -> Application:
    app = Application(settings=_Settings(APP_HTTP_MAX_BODY_BYTES=16))

    @app.post("/echo")
    async def echo(request: Request) -> Response:
        return Response(content=await request.body())

    return app


@pytest.mark.parametrize("size", [15, 16, 17])
async def test_request_body_size_boundary(application: Application, size: int) -> None:
    body = b"x" * size
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/echo", content=body)
    if size <= 16:
        assert response.status_code == 200
        assert response.content == body
    else:
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "request_too_large"


async def test_large_content_length_is_rejected_without_reading_the_body(application: Application) -> None:
    stream_read = False

    async def body() -> AsyncIterator[bytes]:
        nonlocal stream_read
        stream_read = True
        yield b"x"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/echo", content=body(), headers={"Content-Length": "17"})
    assert response.status_code == 413
    assert not stream_read


@pytest.mark.parametrize("declared_length", [None, "1"])
async def test_actual_stream_size_is_limited_and_reading_stops_early(
    application: Application, declared_length: str | None
) -> None:
    chunks_read: list[bytes] = []

    async def body() -> AsyncIterator[bytes]:
        for chunk in (b"a" * 8, b"b" * 8, b"c", b"unread"):
            chunks_read.append(chunk)
            yield chunk

    headers = {} if declared_length is None else {"Content-Length": declared_length}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/echo", content=body(), headers=headers)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"
    assert chunks_read == [b"a" * 8, b"b" * 8, b"c"]


async def test_chunked_body_at_the_limit_is_preserved(application: Application) -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"abcdefgh"
        yield b"ijklmnop"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/echo", content=body())
    assert response.status_code == 200
    assert response.content == b"abcdefghijklmnop"


async def test_size_limit_precedes_json_parsing_and_is_documented(application: Application) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login", content=b'{"password":"' + b"x" * 32, headers={"Content-Type": "application/json"}
        )
        schema = (await client.get("/openapi.json")).json()
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"
    assert "413" in schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
