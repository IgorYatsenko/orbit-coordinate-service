import os

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, multiprocess


class Metrics:
    def __init__(self, *, buckets_sec: tuple[float, ...]) -> None:
        self._registry = CollectorRegistry()
        labels = ("method", "route", "status")
        self._requests = Counter(
            "orbit_http_requests_total", "HTTP requests handled by the application.", labels, registry=self._registry
        )
        self._duration = Histogram(
            "orbit_http_request_duration_seconds",
            "Time spent handling an HTTP request, including sending the response.",
            labels,
            buckets=buckets_sec,
            registry=self._registry,
        )

    def observe(self, *, method: str, route: str, status: int, duration_sec: float) -> None:
        self._requests.labels(method, route, str(status)).inc()
        self._duration.labels(method, route, str(status)).observe(duration_sec)

    def collect(self) -> bytes:
        registry = self._registry
        if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
            # A separate registry prevents exporting both local and aggregated samples.
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
