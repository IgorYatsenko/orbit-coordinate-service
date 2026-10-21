import os
from contextlib import nullcontext
from tempfile import TemporaryDirectory

import uvicorn

from api.logging import configure_logging
from api.settings import get_settings


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.APP_LOG_LEVEL)
    shared_metrics = settings.APP_METRICS_ENABLED and settings.APP_HTTP_WORKERS > 1
    directory_context = TemporaryDirectory(prefix="orbit-metrics-") if shared_metrics else nullcontext()
    with directory_context as directory:
        previous = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if directory is not None:
            # Set before importing the application; spawned workers inherit this directory.
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = directory
        try:
            uvicorn.run(
                "api.main:create_app",
                factory=True,
                host=settings.APP_HOST,
                port=settings.APP_PORT,
                workers=settings.APP_HTTP_WORKERS,
                log_config=None,
                log_level=settings.APP_LOG_LEVEL.lower(),
                timeout_keep_alive=settings.APP_HTTP_KEEP_ALIVE_SEC,
                timeout_graceful_shutdown=settings.APP_SHUTDOWN_TIMEOUT_SEC,
                proxy_headers=bool(settings.APP_HTTP_TRUSTED_PROXY_IPS),
                forwarded_allow_ips=settings.APP_HTTP_TRUSTED_PROXY_IPS,
            )
        finally:
            if previous is None:
                os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
            else:
                os.environ["PROMETHEUS_MULTIPROC_DIR"] = previous


if __name__ == "__main__":
    main()
