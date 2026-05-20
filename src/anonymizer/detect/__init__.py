"""Detection pipeline: regex rules first, then NER over unclaimed spans."""

from __future__ import annotations

import re

from anonymizer.detect import ner, regex_rules
from anonymizer.replace import Span


def _resolve(spans: list[Span]) -> list[Span]:
    """Drop overlapping spans; earlier start wins, longer wins on a tie."""
    ordered = sorted(spans, key=lambda s: (s.start, -s.end))
    kept: list[Span] = []
    last_end = -1
    for span in ordered:
        if span.start >= last_end:
            kept.append(span)
            last_end = span.end
    return kept


def _overlaps_any(span: Span, others: list[Span]) -> bool:
    return any(span.start < o.end and o.start < span.end for o in others)


def _sweep(text: str, spans: list[Span]) -> list[Span]:
    """Propagate each detected value to its remaining occurrences in ``text``.

    For every distinct ``(category, value)`` among ``spans``, find further exact
    occurrences of ``value`` (word-boundary matched, so a short value is not
    matched inside a longer word) that do not overlap an existing span, and
    return them as new spans of the same category. Closes NER recall gaps where
    an entity is tagged in some sentences but missed in others.
    """
    extra: list[Span] = []
    for category, value in {(s.category, s.value) for s in spans}:
        if len(value) < 2 or "{{" in value:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.UNICODE)
        for match in pattern.finditer(text):
            found = Span(match.start(), match.end(), category, value)
            if not _overlaps_any(found, spans):
                extra.append(found)
    return extra


def detect_all(text: str, options) -> list[Span]:
    """Detect all private-data spans in ``text``.

    Regex rules run first and take priority; NER spans are kept only where they
    do not overlap a regex match. A consistency sweep then propagates every
    detected value to its other occurrences (unless disabled on ``options``).
    """
    regex_spans = _resolve(regex_rules.detect(text))

    ner_spans: list[Span] = []
    for span in _resolve(ner.detect(text, options)):
        if not _overlaps_any(span, regex_spans):
            ner_spans.append(span)

    detected = regex_spans + ner_spans
    if options.consistency_sweep:
        detected = detected + _sweep(text, detected)
    return _resolve(detected)
