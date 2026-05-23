"""Curated exclusion dictionaries and stoplists for detection.

Each ``dict_<name>.json`` file here holds one hand-curated word list as a JSON
resource. Detection code (``regex_rules.py``, ``ner.py``) loads these lists via
:func:`load`; editing a list means editing only its JSON file, not detection
logic. Regex patterns and structural fragments stay in the detection modules —
only curated word lists live here.

Each JSON file is an object with a ``description`` field (the list's purpose
and how to extend it — JSON has no comments, so the note lives in the data)
and either an ``items`` array or a ``groups`` object mapping group names to
item arrays (used by ``dict_tech_terms`` to keep entries grouped by kind).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

_DICT_DIR = Path(__file__).parent


@cache
def load(name: str) -> tuple[str, ...]:
    """Return the word list from ``dict_<name>.json`` as a tuple.

    A file with an ``items`` array yields that array; a file with a ``groups``
    object yields every group's items flattened in declaration order. Cached,
    so each file is read once per process.
    """
    data = json.loads((_DICT_DIR / f"dict_{name}.json").read_text("utf-8"))
    if "groups" in data:
        return tuple(item for group in data["groups"].values() for item in group)
    return tuple(data["items"])
