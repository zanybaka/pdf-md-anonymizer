"""Detection spans and reversible token replacement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from anonymizer.categories import Category

# Matches any existing {{...}} placeholder so generated tokens never collide
# with braces already present in the input.
_EXISTING_TOKEN_RE = re.compile(r"\{\{[^{}]*\}\}")


class Span(NamedTuple):
    """A detected fragment of text to be tokenized."""

    start: int
    end: int
    category: Category
    value: str


@dataclass
class AnonResult:
    """Result of :func:`anonymizer.api.anonymize`."""

    text: str
    mapping: dict[str, str]


def _make_token(category: str, n: int) -> str:
    return "{{" + f"{category}_{n}" + "}}"


def replace_spans(text: str, spans: Iterable[Span]) -> AnonResult:
    """Replace detected spans with ``{{CATEGORY_N}}`` tokens.

    Tokens use a per-category 1-based counter; an identical value within a
    category reuses its token. Replacements are applied right-to-left so that
    earlier offsets stay valid. Tokens that would clash with ``{{...}}``
    already present in ``text`` are skipped.
    """
    spans = sorted(spans, key=lambda s: s.start)
    reserved = set(_EXISTING_TOKEN_RE.findall(text))

    counters: dict[str, int] = {}
    value_token: dict[tuple[str, str], str] = {}
    mapping: dict[str, str] = {}

    for span in spans:
        key = (span.category, span.value)
        if key in value_token:
            continue
        n = counters.get(span.category, 0)
        while True:
            n += 1
            token = _make_token(span.category, n)
            if token not in reserved:
                break
        counters[span.category] = n
        reserved.add(token)
        value_token[key] = token
        mapping[token] = span.value

    out = text
    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        token = value_token[(span.category, span.value)]
        out = out[: span.start] + token + out[span.end :]

    return AnonResult(text=out, mapping=mapping)
