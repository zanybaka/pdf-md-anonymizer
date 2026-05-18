"""CORE-003: map serialization and restore round-trip."""

import json

from anonymizer.api import Options, anonymize
from anonymizer.mapping import dumps_map, load_map, restore, write_map
from tests.test_detect import SAMPLE


def test_map_is_sorted_utf8_json():
    mapping = {"{{B_1}}": "вторая", "{{A_1}}": "первая"}
    dumped = dumps_map(mapping)
    assert list(json.loads(dumped)) == ["{{A_1}}", "{{B_1}}"]
    assert "первая" in dumped  # ensure_ascii=False


def test_restore_reverses_anonymize():
    result = anonymize(SAMPLE, Options())
    assert restore(result.text, result.mapping) == SAMPLE


def test_write_and_load_round_trip(tmp_path):
    result = anonymize(SAMPLE, Options())
    map_path = tmp_path / "out.map.json"
    write_map(map_path, result.mapping)
    assert load_map(map_path) == result.mapping
    assert restore(result.text, load_map(map_path)) == SAMPLE
