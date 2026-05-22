"""Natasha NER detection: PERSON, ORG, LOC, with a precision post-filter."""

from __future__ import annotations

import re
import threading
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Protocol

from anonymizer.categories import Category
from anonymizer.detect.dictionaries import load as _load_dict
from anonymizer.detect import structural
from anonymizer.replace import Span

# Curated word lists, loaded from JSON resources in dictionaries/.
# Résumé-specific lists (RESUME_*) live in structural.py.
COLLOQUIAL_WORDS = _load_dict("colloquial_words")
COUNTRY_NAMES = _load_dict("country_names")
DOCUMENT_GRIFS = _load_dict("document_grifs")
GENERIC_NOUNS = _load_dict("generic_nouns")
ORG_ABBREVIATIONS = _load_dict("org_abbreviations")
ORG_FORMS = _load_dict("org_forms")
TECH_TERMS = _load_dict("tech_terms")

_TYPE_TO_CATEGORY = {"PER": Category.PERSON, "ORG": Category.ORG, "LOC": Category.LOC}


@dataclass
class NerContext:
    """Immutable per-call context passed to every SpanFilter."""
    text: str
    skill_ranges: list[tuple[int, int]]
    stoplist: frozenset[str]


class SpanFilter(Protocol):
    """Single-responsibility predicate over a trimmed NER span."""
    name: str

    def keep(
        self,
        span,
        value: str,
        start: int,
        stop: int,
        category: "Category",
        options,
        ctx: NerContext,
    ) -> bool: ...

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
    *structural.RESUME_SECTION_HEADERS,
    *structural.RESUME_FIELD_LABELS,
)

# Casefolded, whitespace-collapsed keys of the curated developer-tool stoplist
# (the tool list itself lives in dictionaries/tech_terms).
_TECH_KEYS: frozenset[str] = frozenset(
    " ".join(t.split()).casefold() for t in TECH_TERMS
)

# Backward-compat alias; logic now lives in structural.py.
_skill_section_ranges = structural.skill_section_ranges

_default: "NerPipeline | None" = None
_default_lock = threading.Lock()


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


# Install the pkg_resources stub once at module import time so pymorphy2's
# entry-point discovery works in Briefcase bundles (no setuptools installed).
# The deprecation warning is suppressed here; subsequent imports are already
# past this point and produce no further warnings.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="pkg_resources is deprecated",
        category=UserWarning,
    )
    _ensure_pkg_resources()


def _build_pipeline(
    on_step: Callable[[str], None] | None = None,
) -> tuple:
    """Construct the NER pipeline, optionally reporting each stage."""

    def _s(msg: str) -> None:
        if on_step:
            on_step(msg)

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


class NerPipeline:
    """Built natasha NER pipeline with an integrated lemma cache and stoplist."""

    def __init__(self, on_step: Callable[[str], None] | None = None) -> None:
        (self._segmenter, self._morph_tagger, self._ner_tagger,
         self._morph_vocab, self._Doc) = _build_pipeline(on_step)
        self._stoplist_keys: frozenset[str] | None = None
        self.lemma_key = lru_cache(maxsize=2048)(self._compute_lemma_key)

    def _compute_lemma_key(self, text: str) -> str:
        """Word-by-word lemmatized, casefolded key — insensitive to declension."""
        doc = self._Doc(text)
        doc.segment(self._segmenter)
        doc.tag_morph(self._morph_tagger)
        parts: list[str] = []
        for token in doc.tokens:
            if re.search(r"\w", token.text):
                token.lemmatize(self._morph_vocab)
                parts.append(token.lemma.casefold())
        return " ".join(parts)

    @property
    def stoplist(self) -> frozenset[str]:
        """Lemma keys of the non-sensitive stoplist, built once on first use."""
        if self._stoplist_keys is None:
            self._stoplist_keys = frozenset(self.lemma_key(t) for t in _STOPLIST_TERMS)
        return self._stoplist_keys

    def _detect_inner(self, text: str, options) -> list[Span]:
        """Run NER on ``text`` with filtering; used by both full-doc and per-line passes."""
        doc = self._Doc(_normalize_caps(text))
        doc.segment(self._segmenter)
        doc.tag_morph(self._morph_tagger)
        doc.tag_ner(self._ner_tagger)
        ctx = NerContext(text, _skill_section_ranges(text), self.stoplist)
        spans: list[Span] = []
        for span in doc.spans:
            category = _TYPE_TO_CATEGORY.get(span.type)
            if category is None:
                continue
            original = text[span.start:span.start + len(span.text)]
            trimmed = _trim(span.start, original)
            if trimmed is None:
                continue
            start, stop, value = trimmed
            if all(f.keep(span, value, start, stop, category, options, ctx) for f in FILTERS):
                spans.append(Span(start, stop, category, value))
        return _merge_hyphenated(text, spans)

    def detect(self, text: str, options) -> list[Span]:
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

        A per-line fallback pass runs after the full-document NER. Natasha's CRF
        model occasionally drops an entity when the surrounding lines provide a
        confusing context (e.g. a bare "/" on the next line). Running NER again on
        each individual line isolates that context and recovers missed spans. The
        fallback re-applies skill-section suppression using full-document ranges so
        that ORG/LOC entities inside skill sections are not incorrectly resurrected.
        """
        full_spans = self._detect_inner(text, options)

        skill_ranges = structural.skill_section_ranges(text)
        extra: list[Span] = []
        pos = 0
        for line in text.split("\n"):
            line_len = len(line)
            if line.strip():
                for span in self._detect_inner(line, options):
                    abs_start = pos + span.start
                    abs_end = pos + span.end
                    if span.category in (Category.ORG, Category.LOC):
                        if structural.is_in_any_range(abs_start, skill_ranges):
                            continue
                    adjusted = Span(abs_start, abs_end, span.category, span.value)
                    if not _overlaps(adjusted, full_spans) and not _overlaps(adjusted, extra):
                        extra.append(adjusted)
            pos += line_len + 1

        if not extra:
            return full_spans

        return _merge_hyphenated(text, full_spans + extra)


def get_default(on_step: Callable[[str], None] | None = None) -> NerPipeline:
    """Return (or build) the module-level singleton NerPipeline."""
    global _default
    if _default is not None:
        return _default
    with _default_lock:
        if _default is None:
            _default = NerPipeline(on_step=on_step)
    return _default


def warmup(on_step: Callable[[str], None] | None = None) -> None:
    """Load the NER pipeline eagerly, reporting each stage via *on_step*."""
    get_default(on_step)


def _lemma_key(text: str) -> str:
    """Delegate to the singleton pipeline's cached lemma_key."""
    return get_default().lemma_key(text)


def _get_stoplist() -> frozenset[str]:
    """Delegate to the singleton pipeline's stoplist."""
    return get_default().stoplist


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


class _CategoryRouting:
    name = "CategoryRouting"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        if category == Category.ORG and not getattr(options, "ner_org", True):
            return False
        if category == Category.LOC and not getattr(options, "ner_loc", True):
            return False
        return True


class _PersonPropn:
    name = "PersonPropn"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        if category == Category.PERSON:
            return _has_propn(span, start, stop)
        return True


class _OrgLocPropn:
    name = "OrgLocPropn"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        if (
            category in (Category.ORG, Category.LOC)
            and getattr(options, "ner_pos_filter", True)
        ):
            return _has_propn_or_foreign(span, start, stop)
        return True


class _SkillSection:
    name = "SkillSection"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        if category in (Category.ORG, Category.LOC):
            return not structural.is_in_any_range(start, ctx.skill_ranges)
        return True


class _TechStoplist:
    name = "TechStoplist"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        if category in (Category.ORG, Category.PERSON):
            return _tech_key(value) not in _TECH_KEYS
        return True


class _LemmaStoplist:
    name = "LemmaStoplist"

    def keep(self, span, value, start, stop, category, options, ctx) -> bool:
        return _lemma_key(value) not in ctx.stoplist


# Ordered filter chain applied to every trimmed NER span.
# CategoryRouting → PersonPropn → OrgLocPropn → SkillSection
# → TechStoplist → LemmaStoplist
# Re-ordering requires an explicit snapshot-test update (see test_ner_filters.py).
FILTERS: tuple[SpanFilter, ...] = (
    _CategoryRouting(),
    _PersonPropn(),
    _OrgLocPropn(),
    _SkillSection(),
    _TechStoplist(),
    _LemmaStoplist(),
)


def detect(text: str, options) -> list[Span]:
    """Detect PERSON, ORG, and LOC spans; delegates to the singleton NerPipeline."""
    return get_default().detect(text, options)
