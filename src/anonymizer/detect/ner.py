"""Natasha NER detection: PERSON, ORG, LOC, with a precision post-filter."""

from __future__ import annotations

import re
import threading
import warnings
from functools import lru_cache
from typing import Callable

from anonymizer.detect.dictionaries import load as _load_dict
from anonymizer.replace import Span

# Curated word lists, loaded from JSON resources in dictionaries/.
COLLOQUIAL_WORDS = _load_dict("colloquial_words")
COUNTRY_NAMES = _load_dict("country_names")
DOCUMENT_GRIFS = _load_dict("document_grifs")
GENERIC_NOUNS = _load_dict("generic_nouns")
ORG_ABBREVIATIONS = _load_dict("org_abbreviations")
ORG_FORMS = _load_dict("org_forms")
RESUME_FIELD_LABELS = _load_dict("resume_field_labels")
RESUME_SECTION_HEADERS = _load_dict("resume_section_headers")
RESUME_SKILL_SECTION_STEMS = _load_dict("resume_skill_section_stems")
TECH_TERMS = _load_dict("tech_terms")

_TYPE_TO_CATEGORY = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}

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

# The twelve Russian month names — Natasha mistags them as PERSON on résumé
# date ranges ("Май", "Декабрь"). "Май" is morphologically PROPN, so the POS
# filter cannot catch it; the stoplist lemma-matches, so declensions are
# covered.
_MONTH_NAMES: tuple[str, ...] = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)

# Non-sensitive terms Natasha NER tends to mistag — country names, document
# grifs, generic nouns, colloquial filler words, bare legal forms (a legal form
# alone names no specific organization), month names, and résumé section
# headers / field labels. Each group is sourced from its own dictionaries/
# module; only _MONTH_NAMES (a fixed, universal list, not an open-ended
# exclusion dictionary) stays inline. Compared as word-by-word lemma keys, so
# any declension matches (e.g. "Общества с ограниченной ответственностью").
_STOPLIST_TERMS: tuple[str, ...] = (
    *COUNTRY_NAMES,
    *DOCUMENT_GRIFS,
    *GENERIC_NOUNS,
    *COLLOQUIAL_WORDS,
    *ORG_FORMS,
    *ORG_ABBREVIATIONS,
    *_MONTH_NAMES,
    *RESUME_SECTION_HEADERS,
    *RESUME_FIELD_LABELS,
)

# Casefolded, whitespace-collapsed keys of the curated developer-tool stoplist
# (the tool list itself lives in dictionaries/tech_terms).
_TECH_KEYS: frozenset[str] = frozenset(
    " ".join(t.split()).casefold() for t in TECH_TERMS
)

# A markdown ATX header line: leading #'s (depth), then the heading text.
_HEADER_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

def _skill_section_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of skills/technologies/competencies sections.

    A section starts at a markdown header whose text names a skills block (see
    ``RESUME_SKILL_SECTION_STEMS``) and runs to the next header of the same or
    shallower depth, or to the end of the text. ``ORG``/``LOC`` spans starting
    inside any returned range are dropped — see ADR-0007.
    """
    headers = [
        (m.start(), len(m.group(1)), m.group(2))
        for m in _HEADER_RE.finditer(text)
    ]
    ranges: list[tuple[int, int]] = []
    for i, (pos, depth, title) in enumerate(headers):
        folded = title.casefold()
        if not any(stem in folded for stem in RESUME_SKILL_SECTION_STEMS):
            continue
        end = len(text)
        for next_pos, next_depth, _title in headers[i + 1:]:
            if next_depth <= depth:
                end = next_pos
                break
        ranges.append((pos, end))
    return ranges

# (Segmenter, NewsMorphTagger, NewsNERTagger, MorphVocab, Doc) — built once,
# the model is the costly part.
_pipeline = None
_pipeline_lock = threading.Lock()
# Lemma keys of _STOPLIST_TERMS — built once, lazily (needs the pipeline).
_stoplist_keys: frozenset[str] | None = None


def _ensure_pkg_resources() -> None:
    """Inject a minimal pkg_resources stub when setuptools is not installed.

    Briefcase bundles Python without setuptools; pymorphy2 imports
    pkg_resources (deprecated) to discover dict backends via entry points.
    importlib.metadata (stdlib ≥ 3.9) provides the same data without
    setuptools, so we wire it in when the real module is absent.
    """
    try:
        import pkg_resources  # noqa: F401
        return
    except ImportError:
        pass
    import importlib.metadata
    import sys
    import types

    mod = types.ModuleType("pkg_resources")

    class _WorkingSet:
        def iter_entry_points(self, group: str):  # type: ignore[override]
            try:
                return iter(importlib.metadata.entry_points(group=group))
            except Exception:
                return iter([])

    mod.WorkingSet = _WorkingSet  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = mod


def _build_pipeline(
    on_step: Callable[[str], None] | None = None,
) -> tuple:
    """Construct the NER pipeline, optionally reporting each stage."""

    def _s(msg: str) -> None:
        if on_step:
            on_step(msg)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="pkg_resources is deprecated",
            category=UserWarning,
        )
        _ensure_pkg_resources()
        _s("importing natasha…")
        from natasha import (  # noqa: PLC0415
            Doc,
            MorphVocab,
            NewsEmbedding,
            NewsMorphTagger,
            NewsNERTagger,
            Segmenter,
        )
        _s("loading embedding…")
        emb = NewsEmbedding()
        _s("morph tagger…")
        morph = NewsMorphTagger(emb)
        _s("NER tagger…")
        ner = NewsNERTagger(emb)
        _s("vocab…")
        return (Segmenter(), morph, ner, MorphVocab(), Doc)


def warmup(on_step: Callable[[str], None] | None = None) -> None:
    """Load the NER pipeline eagerly, reporting each stage via *on_step*."""
    global _pipeline
    if _pipeline is not None:
        return
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = _build_pipeline(on_step)


def _get_pipeline() -> tuple:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = _build_pipeline()
    return _pipeline


@lru_cache(maxsize=2048)
def _lemma_key(text: str) -> str:
    """Word-by-word lemmatized, casefolded key — insensitive to declension.

    Both the stoplist terms and each span value are reduced with this same
    function, so an imperfect lemma is harmless as long as it is consistent.
    """
    segmenter, morph_tagger, _ner, morph_vocab, Doc = _get_pipeline()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_morph(morph_tagger)
    parts: list[str] = []
    for token in doc.tokens:
        if re.search(r"\w", token.text):
            token.lemmatize(morph_vocab)
            parts.append(token.lemma.casefold())
    return " ".join(parts)


def _get_stoplist() -> frozenset[str]:
    """Lemma keys of the non-sensitive stoplist, built once on first use."""
    global _stoplist_keys
    if _stoplist_keys is None:
        _stoplist_keys = frozenset(_lemma_key(t) for t in _STOPLIST_TERMS)
    return _stoplist_keys


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


# A hyphen with optional inline (non-newline) spaces on either side. pdf2md
# pads punctuation with spaces, so a hyphenated name written "Слово-Слово"
# arrives as "Слово - Слово" and Natasha tags each half separately.
_SPACED_HYPHEN = re.compile(r"[^\S\n]*-[^\S\n]*")


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
            and _SPACED_HYPHEN.fullmatch(text[prev.end:span.start])
        ):
            merged[-1] = Span(
                prev.start, span.end, prev.category,
                text[prev.start:span.end],
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
        getattr(token, "pos", None) == "PROPN"
        and token.start < stop
        and token.stop > start
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
        getattr(token, "pos", None) in ("PROPN", "X")
        and token.start < stop
        and token.stop > start
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


def detect(text: str, options) -> list[Span]:
    """Detect PERSON, ORG, and LOC spans with Natasha.

    PERSON is always tokenized; ORG/LOC are suppressed by ``ner_org=False`` /
    ``ner_loc=False`` on ``options``. NER runs over a case-normalized copy (see
    ``_normalize_caps``) so ALL-CAPS entities are tagged; because that rewrite
    is length-preserving, each span's offsets index the original text and its
    value is sliced from the original (un-normalized) ``text``. Each span is
    trimmed (clipped at the first newline, edge whitespace/markdown stripped)
    and dropped when its value reduces to a known non-sensitive lemma key.
    Adjacent same-category spans bridged only by a spaced hyphen are then
    merged (see ``_merge_hyphenated``).
    """
    segmenter, morph_tagger, ner_tagger, _vocab, Doc = _get_pipeline()
    doc = Doc(_normalize_caps(text))
    doc.segment(segmenter)
    doc.tag_morph(morph_tagger)
    doc.tag_ner(ner_tagger)
    stoplist = _get_stoplist()
    skill_ranges = _skill_section_ranges(text)

    spans: list[Span] = []
    for span in doc.spans:
        category = _TYPE_TO_CATEGORY.get(span.type)
        if category is None:
            continue
        if category == "ORG" and not getattr(options, "ner_org", True):
            continue
        if category == "LOC" and not getattr(options, "ner_loc", True):
            continue
        original = text[span.start:span.start + len(span.text)]
        trimmed = _trim(span.start, original)
        if trimmed is None:
            continue
        start, stop, value = trimmed
        # POS filter (PERSON): a span with no proper-noun token is a
        # common-noun false positive ("Программист", "Желательное").
        if category == "PERSON" and not _has_propn(span, start, stop):
            continue
        # POS filter (ORG/LOC, NER-007): drop a span built purely from
        # ordinary Russian common-noun-class words — transcript false
        # positives like "Вокруг"/"Канцелярия". A real org/place keeps a
        # PROPN token, a Latin-script company is tagged X — both survive
        # (see _has_propn_or_foreign). Gated by ner_pos_filter: it lowers
        # ORG/LOC recall, so it can be turned off for structured documents.
        if (
            category in ("ORG", "LOC")
            and getattr(options, "ner_pos_filter", True)
            and not _has_propn_or_foreign(span, start, stop)
        ):
            continue
        # Structural suppression: drop an ORG/LOC span that starts inside a
        # skills/technologies/competencies section (ADR-0007). Such a section
        # lists tools, not employers; Natasha mistags the tool names. The
        # curated _TECH_TERMS stoplist below stays as a precision backstop.
        if category in ("ORG", "LOC") and any(
            lo <= start < hi for lo, hi in skill_ranges
        ):
            continue
        # Curated developer-tool stoplist (ORG/PERSON only).
        if category in ("ORG", "PERSON") and _tech_key(value) in _TECH_KEYS:
            continue
        if _lemma_key(value) in stoplist:
            continue
        spans.append(Span(start, stop, category, value))
    return _merge_hyphenated(text, spans)
