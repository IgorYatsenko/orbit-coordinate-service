from time import perf_counter

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.services.metrics import Metrics
from models.pydantic.errors import ErrorDetail, ErrorResponse


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes
        self._too_large = JSONResponse(
            status_code=413,
            content=ErrorResponse(
                detail=ErrorDetail(code="request_too_large", message="Request body exceeds the configured size limit")
            ).model_dump(),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        try:
            content_length = int(Headers(scope=scope).get("content-length", "0"))
        except ValueError:
            content_length = 0
        if content_length > self._max_body_bytes:
            await self._too_large(scope, receive, send)
            return

        # Buffer only a bounded body, so oversized streams never reach the JSON parser.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self._max_body_bytes:
                await self._too_large(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def receive_body() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, receive_body, send)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: Metrics) -> None:
        self._app = app
        self._metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = perf_counter()
        status = 500

        async def send_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, send_response)
        finally:
            matched = scope.get("route")
            route = matched.path if isinstance(matched, Route) else "unmatched"
            if route not in {"/metrics", "/health/live", "/health/ready"}:
                method = scope["method"]
                if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}:
                    method = "OTHER"
                self._metrics.observe(method=method, route=route, status=status, duration_sec=perf_counter() - started)
