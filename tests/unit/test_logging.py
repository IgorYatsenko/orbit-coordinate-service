import json
import logging

from api.logging import JsonFormatter


def test_multiline_message_remains_one_json_record() -> None:
    record = logging.LogRecord("service", logging.WARNING, __file__, 1, "Line one\nLine two: %s", ("value",), None)
    result = JsonFormatter().format(record)
    assert len(result.splitlines()) == 1
    assert json.loads(result)["message"] == "Line one\nLine two: value"
