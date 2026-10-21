from time import perf_counter

from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.services.metrics import Metrics


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
