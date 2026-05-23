"""CORE-003: map serialization and restore round-trip."""

import json

from anonymizer.api import Options, anonymize
from anonymizer.mapping import dumps_map, load_map, restore, write_map
from tests.test_detect import SAMPLE


def test_options_defaults():
    opts = Options()
    assert opts.ner_org is True
    assert opts.ner_loc is True
    assert opts.llm is False
    assert opts.consistency_sweep is True
    assert opts.ner_pos_filter is True
    assert opts.brand_propagation is True


def test_map_is_sorted_utf8_json():
    mapping = {"{{B_1}}": "вторая", "{{A_1}}": "первая"}
    dumped = dumps_map(mapping)
    assert list(json.loads(dumped)) == ["{{A_1}}", "{{B_1}}"]
    assert "первая" in dumped  # ensure_ascii=False
    assert dumped.endswith("\n")  # trailing newline required by serialization contract
    assert '\n  "{{A_1}}"' in dumped  # 2-space indent (indent=2 contract)


def test_restore_reverses_anonymize():
    result = anonymize(SAMPLE, Options())
    assert restore(result.text, result.mapping) == SAMPLE


def test_restore_longest_first_prevents_partial_token_match():
    # {{EMAIL_1}} is a prefix of {{EMAIL_10}}. If tokens were replaced
    # shortest-first, {{EMAIL_1}} inside {{EMAIL_10}} would be substituted
    # first, corrupting the longer token's replacement.
    mapping = {"{{EMAIL_1}}": "a", "{{EMAIL_10}}": "b"}
    text = "{{EMAIL_10}} and {{EMAIL_1}}"
    assert restore(text, mapping) == "b and a"


def test_anonymize_uses_default_options_when_none_passed():
    # Exercises the `options = options or Options()` branch in anonymize().
    result = anonymize("test@example.com")
    assert "{{EMAIL_1}}" in result.text


def test_write_and_load_round_trip(tmp_path):
    result = anonymize(SAMPLE, Options())
    map_path = tmp_path / "out.map.json"
    write_map(map_path, result.mapping)
    assert load_map(map_path) == result.mapping
    assert restore(result.text, load_map(map_path)) == SAMPLE
