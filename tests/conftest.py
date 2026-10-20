from pathlib import Path

import pytest

from models.pydantic import CoordinateRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tle_request() -> CoordinateRequest:
    return CoordinateRequest.model_validate_json((PROJECT_ROOT / "examples/request-tle.json").read_bytes())


@pytest.fixture
def omm_request() -> CoordinateRequest:
    return CoordinateRequest.model_validate_json((PROJECT_ROOT / "examples/request-omm.json").read_bytes())
