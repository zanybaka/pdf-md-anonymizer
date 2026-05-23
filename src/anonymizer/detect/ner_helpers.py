"""Span post-processing helpers for the Natasha NER pipeline.

Split out of ``ner.py`` for file-size reasons. ``ner.py`` re-exports every
public symbol from this module so callers keep using
``from anonymizer.detect.ner import …`` unchanged.

Scope: span-shape utilities (trim, overlap, merge, normalize-caps) and the
POS / tech-stoplist predicates the filter chain uses. Filter classes and the
``FILTERS`` tuple stay in ``ner.py`` per the Phase-8 architectural invariant.
"""

from __future__ import annotations

import re

from anonymizer.categories import Category
from anonymizer.detect.dictionaries import load as _load_dict
from anonymizer.replace import Span

# Curated word lists loaded here because the helpers below depend on them.
ORG_ABBREVIATIONS = _load_dict("org_abbreviations")
TECH_TERMS = _load_dict("tech_terms")

_TYPE_TO_CATEGORY = {"PER": Category.PERSON, "ORG": Category.ORG, "LOC": Category.LOC}

# Whitespace and markdown punctuation trimmed from the edges of a NER span.
_EDGE_CHARS = "#*>- \t\r"

# An ALL-CAPS Cyrillic word: 2+ uppercase letters, hyphens allowed inside
# (e.g. "КРУГЛОВ", "АСТРАЛ-СОФТ"). Single-letter all-caps tokens (the
# conjunction "И") are left alone. Used to normalize case before NER.
_ALLCAPS_WORD = re.compile(r"[А-ЯЁ][А-ЯЁ\-]+")

# Legal-form abbreviations stay uppercase during normalization: "ООО АСТРАЛ-СОФТ"
# → "ООО Астрал-Софт" is the natural-case form Natasha was trained on, so it
# tags the company reliably; title-casing the abbreviation ("Ооо") confuses it.
_ORG_ABBR_SET = frozenset(ORG_ABBREVIATIONS)

# Casefolded, whitespace-collapsed keys of the curated developer-tool stoplist
# (the tool list itself lives in dictionaries/tech_terms).
_TECH_KEYS: frozenset[str] = frozenset(" ".join(t.split()).casefold() for t in TECH_TERMS)

# A hyphen with optional inline (non-newline) spaces on either side. pdf2md
# pads punctuation with spaces, so a hyphenated name written "Слово-Слово"
# arrives as "Слово - Слово" and Natasha tags each half separately.
_SPACED_HYPHEN = re.compile(r"[^\S\n]*-[^\S\n]*")


def _trim(start: int, value: str) -> tuple[int, int, str] | None:
    """Clip a NER span at its first newline and strip edge whitespace/markdown.

    ``value`` is the raw span text starting at offset ``start``. Returns the
    adjusted ``(start, end, value)``, or ``None`` if nothing meaningful remains.
    """
    newline = value.find("\n")
    if newline != -1:
        value = value[:newline]
    lead = len(value) - len(value.lstrip(_EDGE_CHARS))
    trimmed = value.strip(_EDGE_CHARS)
    if not trimmed:
        return None
    new_start = start + lead
    return new_start, new_start + len(trimmed), trimmed


def _tech_key(value: str) -> str:
    """Casefolded, whitespace-collapsed key for developer-tool matching."""
    return " ".join(value.split()).casefold()


def _overlaps(span: Span, others: list[Span]) -> bool:
    return any(span.start < o.end and o.start < span.end for o in others)


def _merge_hyphenated(text: str, spans: list[Span]) -> list[Span]:
    """Merge adjacent same-category spans bridged only by a spaced hyphen.

    When two consecutive spans share a category and the gap between them is
    just a hyphen with optional inline spaces, they are the two halves of one
    hyphenated entity (a pdf2md punctuation-spacing artifact) — merge them so a
    single token replaces the whole name. A real ``слово - слово`` separator
    is untouched: its right half is not an entity, so there is no same-category
    neighbour to merge with.
    """
    if not spans:
        return spans
    ordered = sorted(spans, key=lambda s: s.start)
    merged: list[Span] = [ordered[0]]
    for span in ordered[1:]:
        prev = merged[-1]
        if (
            span.category == prev.category
            and prev.end <= span.start
            and _SPACED_HYPHEN.fullmatch(text[prev.end : span.start])
        ):
            merged[-1] = Span(
                prev.start,
                span.end,
                prev.category,
                text[prev.start : span.end],
            )
        else:
            merged.append(span)
    return merged


def _has_propn(span, start: int, stop: int) -> bool:
    """True if any token within ``[start, stop)`` is a proper noun.

    A real ФИО token is tagged ``PROPN`` by the morph tagger; a common noun
    mistagged as PERSON (``Программист``) is ``NOUN``. Only tokens inside the
    trimmed range count — a NER span text can run past a newline into the next
    block (a heading like ``Желательное\\n## …`` pulls in a real name), and a
    ``PROPN`` there must not keep the heading-only span alive.
    """
    return any(
        getattr(token, "pos", None) == "PROPN" and token.start < stop and token.stop > start
        for token in span.tokens
    )


def _has_propn_or_foreign(span, start: int, stop: int) -> bool:
    """True if any token in ``[start, stop)`` is a proper noun or foreign word.

    The ORG/LOC POS filter (NER-007) drops a span only when it is built
    entirely from ordinary Russian common-noun-class words — transcript false
    positives like ``Вокруг`` (``ADV``) or ``Канцелярия`` (``NOUN``). A real
    organization usually carries a ``PROPN`` token; a Latin-script company
    name (``Deutsche Bank``, ``Aker Solutions``) is tagged ``X`` by the morph
    tagger, not ``PROPN``, so ``X`` is kept too — otherwise real foreign
    companies would be dropped. As with :func:`_has_propn`, only tokens inside
    the trimmed range count.
    """
    return any(
        getattr(token, "pos", None) in ("PROPN", "X") and token.start < stop and token.stop > start
        for token in span.tokens
    )


def _normalize_caps(text: str) -> str:
    """Title-case every ALL-CAPS Cyrillic word so Natasha can tag it.

    Natasha's NER model is trained on normal-case news text and misses
    ALL-CAPS entities (signature-block ФИО, unquoted company names). Each
    ALL-CAPS word is rewritten to Title Case (``str.title()`` also capitalizes
    each part of a hyphenated word: ``АСТРАЛ-СОФТ`` → ``Астрал-Софт``), except
    legal-form abbreviations, which stay uppercase. The rewrite is
    length-preserving, so offsets from the normalized copy index the original
    text unchanged.
    """

    def _rewrite(m: re.Match[str]) -> str:
        word = m.group()
        return word if word in _ORG_ABBR_SET else word.title()

    return _ALLCAPS_WORD.sub(_rewrite, text)
