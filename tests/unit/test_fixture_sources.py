import hashlib
import json
from pathlib import Path


def test_captured_celestrak_bytes_match_the_source_manifest() -> None:
    directory = Path(__file__).resolve().parents[1] / "fixtures" / "celestrak"
    sources = json.loads((directory / "sources.json").read_text())
    for source in sources:
        assert hashlib.sha256((directory / source["file"]).read_bytes()).hexdigest() == source["sha256"]
