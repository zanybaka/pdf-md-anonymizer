"""Detection pipeline: regex rules first, then NER over unclaimed spans."""

from __future__ import annotations

import re

from anonymizer.categories import Category
from anonymizer.detect import ner, regex_rules
from anonymizer.replace import Span

# Minimum inner-name length for brand propagation (DETECT-007). A 2-char inner
# name (e.g. "ИТ" mined from "ООО «ИТ-Сервис»" if the trailing-form strip went
# too far) would match inside ordinary Russian words like "литер" — keep the
# floor at 3 to suppress that false-positive class.
_BRAND_MIN_LEN = 3

# Categories of detected spans that can act as a "parent" for a document-
# declared alias (DETECT-008). PERSON / ORG / LOC are the categories Natasha
# tags and that legal documents normally alias; numeric structural categories
# (INN, PHONE, …) have no meaningful alias usage.
_ALIAS_PARENT_CATEGORIES = (Category.PERSON, Category.ORG, Category.LOC)

# Minimum alias length, mirroring _BRAND_MIN_LEN: a 1- or 2-character alias is
# almost always noise and would match inside ordinary words during the sweep.
_ALIAS_MIN_LEN = 3

# Lookback window (non-whitespace characters) before "(далее — …)" where we
# accept a detected span as the alias parent. ~10 characters keeps the rule
# anchored to the immediately-preceding entity while tolerating a closing
# quote / period / brief space run between the parent and the parenthesis.
_ALIAS_PARENT_LOOKBACK_NONWS = 10


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


def _mined_brand(text: str, span: Span, stoplist, lemma_key) -> tuple[Span, str] | None:
    """Narrow ``span`` to its inner company short-name when eligible.

    Returns the narrowed ORG span paired with its inner-name value, or ``None``
    when the span is not a legal-form ORG, the inner name is too short, the
    name is stoplisted, or its position inside the parent match cannot be
    located.
    """
    if span.category != Category.ORG:
        return None
    inner = regex_rules.extract_inner_org_name(span.value)
    if inner is None or len(inner) < _BRAND_MIN_LEN:
        return None
    try:
        if lemma_key(inner) in stoplist:
            return None
    except Exception:  # noqa: BLE001  # morph tagger unavailable mid-test
        return None
    # Locate the inner name inside the parent match. text[span.start:span.end]
    # matches span.value for both regex- and NER-captured ORG spans, so find
    # on the parent text gives the right absolute offset.
    offset = text[span.start : span.end].find(inner)
    if offset < 0:
        return None
    narrowed = Span(
        span.start + offset,
        span.start + offset + len(inner),
        Category.ORG,
        inner,
    )
    return narrowed, inner


def _propagate_short_name(
    text: str, inner: str, existing: list[Span]
) -> tuple[list[Span], list[Span]]:
    """Find every word-bounded occurrence of ``inner`` and return new ORG spans.

    Returns a pair ``(survivors, extra)``: ``survivors`` is ``existing`` with
    any NER LOC/PERSON span dropped that sits exactly at a propagated position,
    and ``extra`` is the new ORG spans added at non-overlapping positions.
    Brand mining is the more specific signal for a captured short-name, so the
    propagated ORG span supersedes a same-position LOC/PERSON tag instead of
    being dropped later by overlap resolution.
    """
    pattern = re.compile(rf"(?<!\w){re.escape(inner)}(?!\w)", re.UNICODE)
    survivors = list(existing)
    extra: list[Span] = []
    for match in pattern.finditer(text):
        found = Span(match.start(), match.end(), Category.ORG, inner)
        if _overlaps_any(found, extra):
            continue
        survivors = [
            s
            for s in survivors
            if not (
                s.category in (Category.LOC, Category.PERSON)
                and s.start == found.start
                and s.end == found.end
            )
        ]
        if not _overlaps_any(found, survivors):
            extra.append(found)
    return survivors, extra


def _brand_propagate(text: str, spans: list[Span]) -> list[Span]:
    """Narrow legal-form ORG spans to the inner name and propagate it.

    For every ORG span whose value starts with a legal form ("ООО «Альфа-Бета»",
    "ООО АСТРАЛ-СОФТ"), pull out the inner company short-name via
    :func:`regex_rules.extract_inner_org_name`. When that name passes the
    minimum-length and stoplist guards, the parent ORG span is replaced with a
    narrowed span anchored on the inner name's position inside the original
    match, and every other non-overlapping word-bounded occurrence of the same
    short-name in ``text`` is added as an ORG span with the same value. Reusing
    the inner-name value lets ``replace_spans`` share one token across the
    legal-form line and every later bare mention, and keeps the round-trip
    exact (the literal ``ООО «...»`` framing stays in the output).
    """
    stoplist = ner._get_stoplist()
    lemma_key = ner._lemma_key

    out: list[Span] = []
    propagated_keys: set[str] = set()
    for span in spans:
        mined = _mined_brand(text, span, stoplist, lemma_key)
        if mined is None:
            out.append(span)
            continue
        narrowed, inner = mined
        out.append(narrowed)
        propagated_keys.add(inner)

    if not propagated_keys:
        return out

    extra: list[Span] = []
    for inner in propagated_keys:
        out, new = _propagate_short_name(text, inner, out)
        extra.extend(new)
    return out + extra


def _lookback_cutoff(text: str, end: int, budget: int) -> int:
    """Return the lowest offset reachable by walking back ``budget`` non-ws chars.

    Walks from ``end`` toward 0, counting non-whitespace characters. Stops once
    ``budget`` non-whitespace characters have been consumed; whitespace is free.
    Returns the offset of the first non-whitespace character that remains
    inside the budget (i.e. spans ending at or after this offset are within
    ``budget`` non-whitespace characters of ``end``).
    """
    cutoff = end
    nonws_seen = 0
    while cutoff > 0 and nonws_seen <= budget:
        cutoff -= 1
        if not text[cutoff].isspace():
            nonws_seen += 1
            if nonws_seen > budget:
                # We stepped one char too far; restore the boundary.
                cutoff += 1
                break
    return cutoff


def _find_alias_parent(text: str, paren_start: int, spans: list[Span]) -> Span | None:
    """Return the detected PERSON / ORG / LOC span immediately preceding ``paren_start``.

    "Immediately" means: the span's ``end`` lies within
    :data:`_ALIAS_PARENT_LOOKBACK_NONWS` non-whitespace characters of
    ``paren_start`` (whitespace between the parent and the parenthesis does
    not count against the budget). When several candidate spans qualify, the
    one that ends closest to the parenthesis wins. Returns ``None`` when no
    detected span sits inside the lookback window — in that case the alias
    has no parent category and is left untokenized.
    """
    cutoff = _lookback_cutoff(text, paren_start, _ALIAS_PARENT_LOOKBACK_NONWS)
    best: Span | None = None
    for span in spans:
        if span.category not in _ALIAS_PARENT_CATEGORIES:
            continue
        if span.end > paren_start or span.end < cutoff:
            continue
        if best is None or span.end > best.end:
            best = span
    return best


def _alias_text_is_valid(alias_text: str, stoplist, lemma_key) -> bool:
    """Filter alias-text candidates: min length, no placeholders, not stoplisted."""
    if len(alias_text) < _ALIAS_MIN_LEN:
        return False
    if "{{" in alias_text or "}}" in alias_text:
        return False
    try:
        return lemma_key(alias_text) not in stoplist
    except Exception:  # noqa: BLE001  # morph tagger unavailable mid-test
        return False


def _alias_span_bounds(text: str, match: re.Match[str]) -> tuple[int, int]:
    """Return the trimmed (start, end) absolute offsets of the alias-text capture.

    ``match.start(1)`` / ``match.end(1)`` give the unstripped capture bounds;
    leading/trailing whitespace inside the capture is stripped so the span
    lines up with the visible alias token.
    """
    cap_start = match.start(1)
    cap_end = match.end(1)
    original = text[cap_start:cap_end]
    leading_ws = len(original) - len(original.lstrip())
    trailing_ws = len(original) - len(original.rstrip())
    return cap_start + leading_ws, cap_end - trailing_ws


def _override_other_category(
    spans: list[Span], alias_text: str, parent_category: Category
) -> list[Span]:
    """Drop spans whose value equals ``alias_text`` but whose category differs.

    The alias declaration overrides Natasha when it tags the alias word with
    the wrong category (e.g. "Заказчик" → ORG when the parent is PERSON).
    """
    return [s for s in spans if not (s.value == alias_text and s.category != parent_category)]


def _alias_propagate(text: str, spans: list[Span]) -> tuple[list[Span], list[Span]]:
    """Capture document-declared aliases of the form ``(далее — Х)`` (DETECT-008).

    Russian legal/contract documents typically declare each party's short alias
    inline (``ООО «Альфа-Бета» (далее — Альфа)``, ``Иванов И.И. (далее
    именуемый Заказчик)``). The alias is then used as a bare capitalised word —
    Natasha sometimes tags it as ORG / LOC, but the *correct* category is the
    parent entity's (PERSON for ``Иванов И.И.``).

    For each ``_ALIAS_RE`` match in ``text``, locate the detected PERSON / ORG
    / LOC span immediately preceding the parenthesis (within ~10 non-whitespace
    characters). If a parent is found and the alias text passes the filters
    (length ≥ 3, not stoplisted, not enclosed in ``{{…}}``), a new span anchored
    at the alias text position inside the parens is returned with the parent's
    category and ``value=alias_text``. Any pre-existing detected span whose
    value equals the alias text and whose category differs from the parent's
    is dropped from ``survivors`` so the alias declaration is the authoritative
    category for that text — the downstream consistency sweep then re-propagates
    the alias under the parent's category at every other occurrence.

    Returns ``(survivors, extra)``: ``survivors`` is ``spans`` with any
    alias-text spans of the wrong category removed, and ``extra`` is the new
    spans anchored on each alias declaration. Aliases without a detected
    parent span are skipped — there is no category to assign — so no orphan
    span is produced.
    """
    stoplist = ner._get_stoplist()
    lemma_key = ner._lemma_key

    survivors = list(spans)
    extra: list[Span] = []
    for match in regex_rules._ALIAS_RE.finditer(text):
        alias_text = match.group(1).strip()
        if not _alias_text_is_valid(alias_text, stoplist, lemma_key):
            continue
        parent = _find_alias_parent(text, match.start(), survivors)
        if parent is None:
            continue
        alias_start, alias_end = _alias_span_bounds(text, match)
        if alias_end - alias_start != len(alias_text):
            # Shouldn't happen — the alias_text came from the same capture —
            # but stay defensive: skip rather than emit a misaligned span.
            continue
        survivors = _override_other_category(survivors, alias_text, parent.category)
        candidate = Span(alias_start, alias_end, parent.category, alias_text)
        if _overlaps_any(candidate, survivors) or _overlaps_any(candidate, extra):
            continue
        extra.append(candidate)
    return survivors, extra


def detect_all(text: str, options) -> list[Span]:
    """Detect all private-data spans in ``text``.

    Regex rules run first and take priority; NER spans are kept only where they
    do not overlap a regex match. Brand propagation then narrows each legal-form
    ORG span to its inner company short-name and propagates it across the
    document (unless disabled on ``options``); alias propagation captures
    document-declared aliases of the form ``(далее — Х)`` after a PERSON / ORG /
    LOC span; a consistency sweep finally propagates every detected value to
    its other occurrences (unless disabled on ``options``).
    """
    regex_spans = _resolve(regex_rules.detect(text, options))

    ner_spans: list[Span] = []
    for span in _resolve(ner.detect(text, options)):
        if not _overlaps_any(span, regex_spans):
            ner_spans.append(span)

    detected = regex_spans + ner_spans
    if getattr(options, "brand_propagation", True):
        detected = _brand_propagate(text, detected)
    survivors, alias_extra = _alias_propagate(text, detected)
    detected = survivors + alias_extra
    if options.consistency_sweep:
        detected = detected + _sweep(text, detected)
    return _resolve(detected)
