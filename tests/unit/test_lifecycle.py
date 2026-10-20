import pytest

from api.services.base import BaseService, BaseServiceHub


class RecordingService(BaseService):
    def __init__(self, *, name: str, events: list[str], fail_start: bool = False, fail_stop: bool = False) -> None:
        self._name = name
        self._events = events
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    async def start(self) -> None:
        self._events.append(f"{self._name}:start")
        if self._fail_start:
            raise RuntimeError("Startup failed")

    async def stop(self) -> None:
        self._events.append(f"{self._name}:stop")
        if self._fail_stop:
            raise RuntimeError("Shutdown failed")

    async def ping(self) -> bool:
        return True


async def test_resources_stop_in_reverse_order() -> None:
    events: list[str] = []
    first = RecordingService(name="first", events=events)
    second = RecordingService(name="second", events=events)
    hub = BaseServiceHub(services=(first, second))
    async with hub.lifespan():
        events.append("request")
    assert events == ["first:start", "second:start", "request", "second:stop", "first:stop"]


async def test_partial_startup_releases_both_started_and_failing_resource() -> None:
    events: list[str] = []
    first = RecordingService(name="first", events=events)
    second = RecordingService(name="second", events=events, fail_start=True)
    third = RecordingService(name="third", events=events)
    hub = BaseServiceHub(services=(first, second, third))
    with pytest.raises(RuntimeError, match="Startup failed"):
        async with hub.lifespan():
            pytest.fail("A failed startup must not serve requests")
    assert events == ["first:start", "second:start", "second:stop", "first:stop"]


async def test_shutdown_error_does_not_leak_other_resources() -> None:
    events: list[str] = []
    first = RecordingService(name="first", events=events)
    second = RecordingService(name="second", events=events, fail_stop=True)
    hub = BaseServiceHub(services=(first, second))
    with pytest.raises(RuntimeError, match="Shutdown failed"):
        async with hub.lifespan():
            pass
    assert events[-2:] == ["second:stop", "first:stop"]
