"""Replacement-map serialization and the inverse :func:`restore` operation."""

from __future__ import annotations

import json
from pathlib import Path


def dumps_map(mapping: dict[str, str]) -> str:
    """Serialize a replacement map as sorted-key UTF-8 JSON."""
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_map(path: str | Path, mapping: dict[str, str]) -> None:
    """Write a replacement map to *path* using :func:`dumps_map`'s format."""
    Path(path).write_text(dumps_map(mapping), encoding="utf-8")


def load_map(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = json.loads(Path(path).read_text(encoding="utf-8"))
    return result


def restore(text: str, mapping: dict[str, str]) -> str:
    """Rebuild the original text by substituting each token with its value.

    Tokens are replaced longest-first so a token can never be replaced inside
    a longer token's name.
    """
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text
