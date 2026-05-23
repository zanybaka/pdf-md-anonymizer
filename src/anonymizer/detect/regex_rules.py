"""Regex and dictionary detectors for structured private data."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from anonymizer.categories import Category
from anonymizer.detect.dictionaries import load as _load_dict
from anonymizer.replace import Span

# Curated word lists, loaded from JSON resources in dictionaries/.
ORG_FORMS = _load_dict("org_forms")
ORG_ABBREVIATIONS = _load_dict("org_abbreviations")
URL_TLDS = _load_dict("url_tlds")


@dataclass(frozen=True)
class Rule:
    name: str
    category: Category
    pattern: re.Pattern[str]
    group: int = 0
    validator: Callable[[str], bool] | None = None
    # Optional gating: when set, the rule is evaluated only if the
    # ``Options`` attribute of the same name is truthy. ``None`` means the
    # rule is always on (the default for the existing identifier rules).
    option_name: str | None = None


def _luhn_ok(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) < 12:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _digits(value: str) -> list[int]:
    """Digit characters of ``value`` as ints — drops separators (SNILS dashes)."""
    return [int(c) for c in value if c.isdigit()]


# ФНС weighted-sum coefficients for the INN control digits. A 10-digit INN has
# one control digit; a 12-digit INN has two (computed over 10 then 11 digits).
_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
# SNILS weighted-sum coefficients over its first 9 digits.
_SNILS_WEIGHTS = (9, 8, 7, 6, 5, 4, 3, 2, 1)


def _inn_check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    """A single INN control digit: weighted sum mod 11, then mod 10."""
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def _inn_ok(value: str) -> bool:
    """Validate a 10- or 12-digit INN by its ФНС control digit(s)."""
    d = _digits(value)
    if len(d) == 10:
        return _inn_check_digit(d[:9], _INN10_WEIGHTS) == d[9]
    if len(d) == 12:
        return (
            _inn_check_digit(d[:10], _INN12_WEIGHTS_11) == d[10]
            and _inn_check_digit(d[:11], _INN12_WEIGHTS_12) == d[11]
        )
    return False


def _ogrn_ok(value: str) -> bool:
    """Validate a 13-digit OGRN: first 12 digits mod 11, mod 10 == last digit."""
    d = _digits(value)
    if len(d) != 13:
        return False
    body = int("".join(str(x) for x in d[:12]))
    return body % 11 % 10 == d[12]


def _ogrnip_ok(value: str) -> bool:
    """Validate a 15-digit OGRNIP: first 14 digits mod 13, mod 10 == last."""
    d = _digits(value)
    if len(d) != 15:
        return False
    body = int("".join(str(x) for x in d[:14]))
    return body % 13 % 10 == d[14]


def _snils_ok(value: str) -> bool:
    """Validate an 11-digit SNILS by its weighted-sum mod-101 control number."""
    d = _digits(value)
    if len(d) != 11:
        return False
    total = sum(x * w for x, w in zip(d[:9], _SNILS_WEIGHTS, strict=False))
    if total > 101:
        total %= 101
    control = 0 if total in (100, 101) else total
    return control == d[9] * 10 + d[10]


# Valid country prefixes for the BIK code (digits 1-2). Per the Central Bank
# of Russia the prefix `04` denotes a Russian BIK; the Bank of Russia also
# allocates `00` for non-Russian (CIS) participants of the national payment
# system. Both are kept here so a legitimate CIS-country BIK that shares the
# format is not silently rejected.
_BIK_COUNTRY_PREFIXES = frozenset({"04", "00"})


def _bik_ok(value: str) -> bool:
    """Structural validation of a 9-digit Russian Bank Identification Code.

    Per the Central Bank of Russia, a БИК is a 9-digit code split into four
    sub-fields: digits 1-2 identify the country (``04`` for Russia, ``00``
    for CIS participants of the national payment system), digits 3-4 the
    region, digits 5-6 the territorial branch of the Central Bank, and
    digits 7-9 the credit organisation. **There is no published mathematical
    control digit for BIK in the public spec**, so this validation is
    purely structural: the value must be exactly 9 digits, the country
    prefix must be in ``_BIK_COUNTRY_PREFIXES``, and the combined
    region-and-territorial sub-field (digits 3-6) must not be all zeros —
    a 9-digit run like ``040000000`` is not a real BIK. The detector still
    requires the ``БИК`` label as the precision gate (no bare-BIK rule),
    so this validator only rejects mis-tokenised non-BIK numbers that
    happen to follow the label.
    """
    d = _digits(value)
    if len(d) != 9:
        return False
    if value[:2] not in _BIK_COUNTRY_PREFIXES:
        return False
    # Region (3-4) and territorial branch (5-6) combined must not be all zero.
    return any(d[2:6])


_IPV6 = r"""(?<![:.\w])(
    (?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}
  | (?:[A-Fa-f0-9]{1,4}:){1,7}:
  | (?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4}
  | (?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}
  | (?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}
  | (?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}
  | (?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}
  | [A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6}
)(?![:.\w])"""

_ORG_ALT = "|".join(re.escape(f) for f in (*ORG_FORMS, *ORG_ABBREVIATIONS))
_ORG_PATTERN = r"\b(?:" + _ORG_ALT + r')\s*[«"“][^»"”]+[»"”]'

# Inner-name extractor (DETECT-007): for a captured ORG value that starts with
# a legal form ("ООО «Альфа-Бета»", "ООО АСТРАЛ-СОФТ", "Общество с ограниченной
# ответственностью «Тест»"), peel off the leading legal-form prefix, optional
# surrounding quotes, and an optional trailing legal-form short word so the
# remainder is the bare company short-name that downstream propagation can
# scan for. Returns ``None`` when the value does not start with a recognised
# legal form — propagation only operates on legal-form-prefixed ORG spans.
_ORG_OPEN_QUOTES = '«"“„'
_ORG_CLOSE_QUOTES = '»"”“'
_INNER_NAME_RE = re.compile(
    r"^\s*" + r"(?:" + _ORG_ALT + r")" + r"\s+" + r"(?P<name>.+?)" + r"\s*$",
    re.IGNORECASE,
)
_TRAILING_ORG_RE = re.compile(
    r"\s+(?:" + _ORG_ALT + r")\s*$",
    re.IGNORECASE,
)


def extract_inner_org_name(value: str) -> str | None:
    """Return the bare company short-name inside a legal-form ORG value.

    For values shaped like ``ООО «Альфа-Бета»`` or ``ООО АСТРАЛ-СОФТ`` strip the
    leading legal-form prefix, surrounding quotes, and a trailing legal-form
    short word if present. Returns ``None`` when the value does not start with
    a recognised legal form, when after stripping nothing meaningful remains,
    or when the leftover is itself a legal-form abbreviation.
    """
    match = _INNER_NAME_RE.match(value)
    if match is None:
        return None
    inner = match.group("name").strip()
    # Strip surrounding quotes (any of the open/close variants we encounter).
    if inner and inner[0] in _ORG_OPEN_QUOTES:
        inner = inner[1:]
    if inner and inner[-1] in _ORG_CLOSE_QUOTES:
        inner = inner[:-1]
    inner = inner.strip()
    # Strip a trailing legal-form abbreviation (e.g. "Альфа НПО" → "Альфа").
    inner = _TRAILING_ORG_RE.sub("", inner).strip()
    if not inner:
        return None
    # A bare legal-form abbreviation alone is not a company short-name.
    if inner.upper() in {f.upper() for f in (*ORG_FORMS, *ORG_ABBREVIATIONS)}:
        return None
    return inner


# Alias-declaration capture (DETECT-008). Russian legal/contract documents
# declare each party's short alias inline, e.g.
#   "ООО «Альфа-Бета» (далее — Альфа)"
#   "Иванов И.И. (далее именуемый Заказчик)"
#   "(далее по тексту — Сторона-1)"
# The alias text is captured in group 1; downstream code in
# ``anonymizer.detect`` looks up the detected span preceding the parenthesis
# and propagates the parent category to every later occurrence of the alias.
# Note: the ``[—\-:]`` separator is kept optional so that the
# ``далее именуем(ый|ая|ое|ые) Х`` shape (no dash) is captured as well — the
# alias-validity filtering (length ≥ 3, stoplist, no nested ``{{…}}``) gates
# noise downstream.
_ALIAS_RE = re.compile(
    r"\(\s*далее"
    r"(?:\s+(?:по\s+тексту|именуем(?:ый|ая|ое|ые)))?"
    r"\s*[—\-:]?\s*"
    r"([^)]+?)\s*\)",
    re.IGNORECASE,
)


# Russian patronymic suffixes — the precision anchor for the ALL-CAPS ФИО rule.
# A capitalised word triple alone is not a name; the patronymic suffix is what
# makes a three-word match a person. Longer suffixes come first so the
# alternation does not stop early on a shared tail (e.g. "ИЧ" inside "ОВИЧ").
_PATRONYMIC = r"(?:ОВИЧ|ЕВИЧ|ИНИЧНА|ОВНА|ЕВНА|ЬИЧ|ИЧ)"
# Three Cyrillic words where the last ends in a patronymic suffix. Matched
# case-insensitively so it catches all-caps signature-block ФИО (which Natasha,
# trained on normal-case news text, misses) and complements NER on normal-case
# ФИО too — regex wins over NER on overlap, so there is no double-tokenization.
_PERSON_PATTERN = r"\b[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]*" + _PATRONYMIC + r"\b"

# Signature-context label anchor: a colon/hyphen/em-dash after a signature
# keyword turns the next capitalised Cyrillic token into a single surname.
# Only the captured surname becomes the span — the label stays in the document.
# The label alternation is case-insensitive (УКЭП/укэп/Подписант all match);
# the surname class is case-sensitive so a lowercase common noun does not
# match. Minimum three Cyrillic letters in the surname keeps initials and
# two-letter junk out. Ordered after the CORE-005 patronymic-triple rule so
# `подписант: ИВАНОВ ИВАН ИВАНОВИЧ` is captured as the full ФИО (the longer
# span wins overlap resolution), not just the surname.
_PERSON_SIGNATURE_PATTERN = (
    r"(?i:УКЭП|подписант|подписал|подписавший|подписывающий"
    r"|ФИО|фамилия|инициалы|подпись)"
    r"\s*[:\-—]\s*([А-ЯЁ][А-ЯЁа-яё\-]{2,})\b"
)

# Alternation of known URL top-level domains for the scheme-less bare-domain
# branch of the URL rule (the TLD list itself lives in dictionaries/url_tlds).
_URL_TLD = "|".join(URL_TLDS)

# Biometric-mention descriptors (DETECT-009). Anchored on Cyrillic word
# boundaries so a stem cannot match inside a longer word; case-insensitive so
# title-case and ALL-CAPS forms both match. Multi-word entries are kept literal
# (the inflection space here is small enough that listing the canonical forms
# is more precise than a stem regex). Listed longest-first so a longer match
# wins over a shorter overlapping branch (e.g. `голосовой отпечаток` over the
# bare `отпечаток пальца` near-miss; `радужная оболочка глаза` over the bare
# `радужная оболочка` substring).
_BIOMETRIC_PATTERN = (
    r"(?<![А-Яа-яёЁ])(?:"
    r"биометрические\s+данные"
    r"|генетические\s+данные"
    r"|голосов(?:ой|ая)\s+отпечаток"
    r"|голосовая\s+модель"
    r"|радужная\s+оболочка(?:\s+глаза)?"
    r"|отпечаток\s+пальца"
    r"|ДНК"
    r")(?![А-Яа-яёЁ])"
)

# Job-title and education-qualification label-anchored patterns (DETECT-013).
# ФЗ-152 lists place of work / position / education as PII; the present
# detector catches employer/university *names* via Natasha NER, but the
# *role text* itself («директор», «инженер», «магистр», «бакалавр») is a
# common noun NER never tags. Two opt-in label-anchored rules capture
# the free-text value listed after a Russian résumé label.
#
# The separator is `\s*[:—\-]\s*` — at least one non-whitespace anchor
# character (`:`, em-dash, or hyphen). A pure-whitespace separator is
# rejected on purpose so that free-text usages like «должность позволяет
# ему» (no colon, common-noun follow-on) do **not** match. A leading
# capital-letter anchor on the captured value is NOT used because
# legitimate qualification values like «магистр информатики» start with a
# lowercase Cyrillic letter — the non-whitespace separator is the precision
# gate here instead.
#
# The capture body is `[^\n,;.]+` — everything from the separator up to the
# next end-of-line, comma, semicolon, or period. The terminating `.` keeps
# `Должность: Главный инженер.` from sweeping in the trailing period (which
# `[^\n,;]+` would otherwise greedy-match), and naturally splits two-clause
# lines like `Должность: Главный инженер. Образование: магистр информатики`
# into two distinct captures.
#
# The label part is case-insensitive via the outer compile-time
# ``re.IGNORECASE`` flag; the capture body remains case-sensitive in the
# sense that the rule itself does not normalise it. Both rules share a
# single umbrella ``Category.OCCUPATION`` — the values are neither
# organisations nor persons, so a dedicated category keeps the downstream
# replacement layer (and the QA-001 baseline_metrics) honest. Off by default;
# opt-in via ``Options.occupation`` plus a CLI flag ``--occupation``.
_JOB_TITLE_PATTERN = (
    r"(?:занимаемая\s+должность|должность|роль)"
    r"\s*[:—\-]\s*"
    r"([^\n,;.]+)"
)
_EDUCATION_PATTERN = (
    r"(?:образование|квалификация|специальность"
    r"|учёная\s+степень|учен(?:ая|ый)\s+степень)"
    r"\s*[:—\-]\s*"
    r"([^\n,;.]+)"
)

# Family-relation label-anchored pattern (DETECT-012). ФЗ-152 lists family
# status as PII; this opt-in rule captures the names of family members
# introduced by a relation label («Супруга», «дети», «сын», …). The names
# themselves are ``Category.PERSON`` — the relation noun is descriptive context
# that stays in the document. The label part is case-insensitive via inline
# ``(?i:…)`` so a mid-sentence ``дети:`` after a semicolon matches as well as a
# sentence-leading ``Супруга:``; the captured name remains case-sensitive
# (``[А-ЯЁ]`` first character) so a lowercase common-noun follow-on like
# «программистов» does **not** match. The capture covers 1-3 capitalised
# Cyrillic words — enough for ``Фамилия Имя Отчество`` without sweeping in a
# trailing common-noun phrase. The relation noun list is small and lives inline
# (no JSON dictionary) — adding a new label is a one-line edit here.
_FAMILY_RELATION_NAME_UNIT = r"[А-ЯЁ][А-Яа-яёЁ\-]+(?:\s+[А-ЯЁ][А-Яа-яёЁ\-]+){0,2}"
_FAMILY_RELATION_PATTERN = (
    r"(?i:супруг(?:а|и|ой)?|дети|сын|дочь|родители|отец|мать|брат|сестра)"
    r"[:\s—\-]+"
    rf"({_FAMILY_RELATION_NAME_UNIT})"
)
_FAMILY_RELATION_RE = re.compile(_FAMILY_RELATION_PATTERN)
# Continuation: after the first captured name, a comma-separated trailing name
# list (``Иванов Пётр, Иванова Мария``) is a single semantic unit under the
# same relation label. The comma anchor is the precision gate — a semicolon
# or sentence end terminates the list, and a verb / common noun (lowercase
# leading character) does not match the capitalised-name unit. Each
# continuation name becomes its own PERSON span so individual tokens can be
# assigned per name.
_FAMILY_RELATION_CONTINUATION_RE = re.compile(rf"\s*,\s*({_FAMILY_RELATION_NAME_UNIT})")

# Medical-data label-anchored patterns (DETECT-010). ФЗ-152 lists medical data
# as PII; the rules are all label-anchored, so the false-positive risk is low
# and they ship always-on (no Options gating). All four sub-rules share a
# single umbrella ``Category.MEDICAL`` — the audit row lumps them together and
# the downstream replacement layer only cares about the category.
#
# ОМС: a 16-digit run preceded by ``Полис ОМС`` / ``ОМС``. Real OMS numbers do
# not satisfy the Luhn check (so the existing CARD rule misses them); a label
# anchor is the precision gate here, not a checksum.
_OMS_PATTERN = r"(?:полис\s+ОМС|ОМС)[:\s№N]*(\d{16})(?!\d)"
# ДМС: policy numbers have no canonical format ("AB-100500", "0123-4567-89")
# so the rule captures the next non-whitespace run after a label. Less precise
# than ОМС, hence the explicit label requirement.
_DMS_PATTERN = r"(?:полис\s+ДМС|ДМС)[:\s№N]*(\S+)"
# Free-text diagnosis / anamnesis / medical-history line. Captures everything
# from the colon/space separator to end-of-line — the same shape as the
# existing ``PASSPORT_ISSUER`` rule.
_DIAGNOSIS_PATTERN = r"(?:диагноз|анамнез|история\s+болезни)[:\s]*([^\n]+)"
# МКБ-10 code (``A00.0`` … ``Z99.9``). The code itself is always uppercase
# Latin, so the code capture is case-sensitive — without that anchor, lowercase
# tokens like ``i10.0`` (an ID, not an ICD-10 code) would match. The rule
# additionally requires an immediately preceding medical label (``диагноз``,
# ``анамнез``, ``МКБ``, ``МКБ-10``, ``код МКБ``) so a bare ``A10.1`` in a table
# of contents is **not** matched. The label part is case-insensitive (via the
# inline ``(?i:…)`` group) so ``Диагноз``/``ДИАГНОЗ``/``диагноз`` all match;
# the code capture remains case-sensitive because the rule is compiled without
# ``re.IGNORECASE``.
_ICD10_PATTERN = (
    r"(?i:диагноз|анамнез|МКБ(?:-10)?|код\s+МКБ)"
    r"[:\s№\-]*"
    r"([A-Z]\d{2}(?:\.\d{1,2})?)\b"
)

# Order matters: earlier rules win ties during overlap resolution.
RULES: list[Rule] = [
    Rule("EMAIL", Category.EMAIL, re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # @-style nickname mentions. No lookbehind is used so that consecutive
    # mentions like @alice@bob are both caught. A bare "@" or "@123" (no
    # leading letter after @) is still rejected by the lookahead (?=[a-zA-Z]).
    # vasily@example.com is handled entirely by the EMAIL rule above: EMAIL
    # wins the overlap during _resolve because it is ordered first and its
    # span fully contains the @domain.tld substring.
    Rule("NICKNAME", Category.NICKNAME, re.compile(r"@(?=[a-zA-Z])[a-zA-Z0-9_.\-]{1,50}")),
    # URL: a scheme URL, a "www." host, or a scheme-less bare domain anchored
    # on a known TLD (catches markdown link text like "[www.site.com/x](…)"
    # and a plain "unicum.ru", neither of which carries an "https://" prefix).
    Rule(
        "URL",
        Category.URL,
        re.compile(
            r"https?://[^\s<>()\[\]«»]+"
            r"|www\.[^\s<>()\[\]«»]+"
            r"|\b(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+(?:" + _URL_TLD + r")\b"
            r"(?:/[^\s<>()\[\]«»]*)?",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "SECRET_PEM",
        Category.SECRET,
        re.compile(r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.DOTALL),
    ),
    Rule(
        "SECRET_KEY_VALUE",
        Category.SECRET,
        re.compile(
            r"(?:password|passwd|pwd|api[_\-]?key|apikey|secret|token|access[_\-]?key)"
            r"\s*[=:]\s*(\S+)",
            re.IGNORECASE,
        ),
        group=1,
    ),
    # Certificate serial: a "№"-prefixed run of 20+ uppercase hex characters.
    # The high-entropy SECRET rule requires mixed case, so an all-caps hex
    # serial slips past it; the "№" anchor keeps this rule from over-matching.
    Rule("SECRET_HEX_SERIAL", Category.SECRET, re.compile(r"№\s*([0-9A-F]{20,})\b"), group=1),
    Rule("ORG", Category.ORG, re.compile(_ORG_PATTERN, re.IGNORECASE)),
    Rule(
        "PASSPORT_LABELED",
        Category.PASSPORT,
        re.compile(r"паспорт[:\s]*(\d{4}\s?\d{6})", re.IGNORECASE),
        group=1,
    ),
    Rule(
        "PASSPORT_ISSUE_DATE",
        Category.PASSPORT,
        re.compile(r"(?:дата выдачи)[:\s]*(\d{2}[./]\d{2}[./]\d{4})", re.IGNORECASE),
        group=1,
    ),
    Rule(
        "PASSPORT_DEPT_CODE",
        Category.PASSPORT,
        re.compile(r"код подразделения[:\s]*(\d{3}-\d{3})", re.IGNORECASE),
        group=1,
    ),
    Rule(
        "PASSPORT_ISSUER",
        Category.PASSPORT,
        re.compile(r"(?:кем выдан|орган выдачи)[:\s]*([^\n]+)", re.IGNORECASE),
        group=1,
    ),
    # Label-anchored: requires a colon after the (optionally qualified) "адрес"
    # label, so plural "адреса средств …" is not mistaken for an address.
    Rule(
        "ADDRESS_LABELED",
        Category.ADDRESS,
        re.compile(r"\bадрес\w*(?:\s+[А-Яа-яёЁ]+){0,2}\s*:\s*([^\n]+)", re.IGNORECASE),
        group=1,
    ),
    Rule(
        "ADDRESS_INLINE",
        Category.ADDRESS,
        re.compile(
            r"\bг\.\s?[А-ЯЁ][^\n,]*(?:,\s*(?:ул|улица|пер|просп|пр-?кт|пр-?т|д|дом"
            r"|кв|корп|стр|оф)\.?\s?[^\n,]+)+",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "SNILS_LABELED",
        Category.SNILS,
        re.compile(r"СНИЛС[:\s]*(\d{3}-\d{3}-\d{3}[\s\-]\d{2})", re.IGNORECASE),
        group=1,
        validator=_snils_ok,
    ),
    Rule(
        "SNILS_BARE",
        Category.SNILS,
        re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[\s\-]\d{2}(?!\d)"),
        validator=_snils_ok,
    ),
    Rule(
        "INN_LABELED",
        Category.INN,
        re.compile(r"ИНН[:\s]*(\d{10}(?:\d{2})?)(?!\d)", re.IGNORECASE),
        group=1,
        validator=_inn_ok,
    ),
    Rule("KPP", Category.KPP, re.compile(r"КПП[:\s]*(\d{9})(?!\d)", re.IGNORECASE), group=1),
    Rule(
        "BIK",
        Category.BIK,
        re.compile(r"БИК[:\s]*(\d{9})(?!\d)", re.IGNORECASE),
        group=1,
        validator=_bik_ok,
    ),
    Rule(
        "OGRNIP_LABELED",
        Category.OGRNIP,
        re.compile(r"ОГРНИП[:\s]*(\d{15})(?!\d)", re.IGNORECASE),
        group=1,
        validator=_ogrnip_ok,
    ),
    Rule("OGRNIP_BARE", Category.OGRNIP, re.compile(r"(?<!\d)\d{15}(?!\d)"), validator=_ogrnip_ok),
    Rule(
        "OGRN_LABELED",
        Category.OGRN,
        re.compile(r"ОГРН[:\s]*(\d{13})(?!\d)", re.IGNORECASE),
        group=1,
        validator=_ogrn_ok,
    ),
    Rule("OGRN_BARE", Category.OGRN, re.compile(r"(?<!\d)\d{13}(?!\d)"), validator=_ogrn_ok),
    # Bare INN — a label-free 10- or 12-digit run, made safe only by the
    # checksum gate (DETECT-002). Ordered after the label-anchored INN and the
    # bare OGRN/OGRNIP rules so those win ties during overlap resolution. The
    # 13/15-digit OGRN/OGRNIP runs cannot match here: the `(?!\d)` boundary
    # rejects a 10/12-digit prefix of a longer digit run.
    Rule(
        "INN_BARE", Category.INN, re.compile(r"(?<!\d)(?:\d{12}|\d{10})(?!\d)"), validator=_inn_ok
    ),
    Rule(
        "ACCOUNT_LABELED",
        Category.ACCOUNT,
        re.compile(
            r"(?:расч[её]тный сч[её]т|р/сч|р/с|к/с|сч[её]т|сч\.)[:\s№N]*(\d{20})(?!\d)",
            re.IGNORECASE,
        ),
        group=1,
    ),
    Rule("ACCOUNT_BARE", Category.ACCOUNT, re.compile(r"(?<!\d)\d{20}(?!\d)")),
    Rule(
        "CARD",
        Category.CARD,
        re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)"),
        validator=_luhn_ok,
    ),
    Rule(
        "PHONE",
        Category.PHONE,
        re.compile(r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"),
    ),
    Rule("PASSPORT_BARE", Category.PASSPORT, re.compile(r"(?<!\d)\d{4}\s\d{6}(?!\d)")),
    Rule(
        "POSTAL_CODE",
        Category.POSTAL_CODE,
        re.compile(r"(?:почтовый индекс|индекс)[:\s]*(\d{6})(?!\d)", re.IGNORECASE),
        group=1,
    ),
    # DOB is label-anchored only: a bare date carries no birth-date meaning, so
    # only dates next to "дата рождения" / "д.р." / "родился"/"родилась" are
    # tokenized. The date may be numeric (ДД.ММ.ГГГГ, ГГГГ-ММ-ДД) or written
    # with a Russian month name ("16 января 1983").
    Rule(
        "DOB",
        Category.DOB,
        re.compile(
            r"(?:дата рождения|д[./]р[.:]?|родил(?:ся|ась))[:\s]*"
            r"(\d{2}[./]\d{2}[./]\d{4}|\d{4}-\d{2}-\d{2}"
            r"|\d{1,2}\s+[а-яё]+\s+\d{4})",
            re.IGNORECASE,
        ),
        group=1,
    ),
    Rule(
        "IP_V4",
        Category.IP,
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    ),
    Rule("IP_V6", Category.IP, re.compile(_IPV6, re.VERBOSE), group=1),
    Rule("PERSON", Category.PERSON, re.compile(_PERSON_PATTERN, re.IGNORECASE)),
    Rule(
        "PERSON_SIGNATURE",
        Category.PERSON,
        re.compile(_PERSON_SIGNATURE_PATTERN),
        group=1,
    ),
    Rule(
        "SECRET_HIGH_ENTROPY",
        Category.SECRET,
        re.compile(
            r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])"
            r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{24,}(?![A-Za-z0-9])"
        ),
    ),
    # Medical-data label-anchored rules (DETECT-010). All four share
    # ``Category.MEDICAL`` (single umbrella, matches the DETECT-006 audit row).
    # Always-on — every rule requires an explicit Russian medical label, so
    # the FP rate is low, matching the existing label-anchored INN/OGRN/etc
    # rules. The free-text DIAGNOSIS rule with ``[^\n]+`` swallows the rest of
    # the line (including any ICD-10 code on the same diagnosis line); the
    # ICD10 rule then catches a context-anchored code that appears under a
    # ``МКБ-10`` / ``код МКБ`` label, where DIAGNOSIS does not apply. Ordered
    # before the broad SECRET_HIGH_ENTROPY / BIOMETRIC_MENTION rules so the
    # medical category wins ties on a same-position match.
    Rule(
        "OMS",
        Category.MEDICAL,
        re.compile(_OMS_PATTERN, re.IGNORECASE),
        group=1,
    ),
    Rule(
        "DMS",
        Category.MEDICAL,
        re.compile(_DMS_PATTERN, re.IGNORECASE),
        group=1,
    ),
    Rule(
        "DIAGNOSIS",
        Category.MEDICAL,
        re.compile(_DIAGNOSIS_PATTERN, re.IGNORECASE),
        group=1,
    ),
    # ICD10: compiled WITHOUT ``re.IGNORECASE`` — the code capture must stay
    # uppercase Latin (МКБ-10 codes are always uppercase). The label part
    # carries its own inline ``(?i:…)`` group.
    Rule(
        "ICD10",
        Category.MEDICAL,
        re.compile(_ICD10_PATTERN),
        group=1,
    ),
    # Biometric-mention surface-text rule (DETECT-009). Opt-in via
    # ``Options.biometric_mentions``; off by default because the mention itself
    # is descriptive, not identifying. Ordered last so any future overlapping
    # identifier rule wins ties — biometric mentions are an additive umbrella
    # category, not a primary identifier.
    Rule(
        "BIOMETRIC_MENTION",
        Category.BIOMETRIC,
        re.compile(_BIOMETRIC_PATTERN, re.IGNORECASE),
        option_name="biometric_mentions",
    ),
    # Family-relation label-anchored rule (DETECT-012). Opt-in via
    # ``Options.family_relations``; off by default because the regex is
    # broader than the existing identifier rules (a capitalised proper name
    # follows the label, gated only by the case-sensitive capital-letter
    # anchor). The rule captures the FIRST name after each relation label;
    # any trailing comma-separated names in the same list are picked up by
    # :func:`_detect_family_continuation_names` immediately below.
    Rule(
        "FAMILY_RELATION",
        Category.PERSON,
        _FAMILY_RELATION_RE,
        group=1,
        option_name="family_relations",
    ),
    # Job-title and education-qualification label-anchored rules (DETECT-013).
    # Opt-in via ``Options.occupation``; off by default because the rules are
    # precision-risky — the capture body sweeps everything up to the next
    # `,`, `;`, `.`, or end-of-line, which on a non-résumé document with a
    # stray «должность» label would inflate the redaction surface beyond
    # strict identifier removal. Both rules share ``Category.OCCUPATION``;
    # the label noun («Должность», «Образование», …) stays verbatim in the
    # document — only the role / qualification value becomes the span.
    Rule(
        "JOB_TITLE",
        Category.OCCUPATION,
        re.compile(_JOB_TITLE_PATTERN, re.IGNORECASE),
        group=1,
        option_name="occupation",
    ),
    Rule(
        "EDUCATION",
        Category.OCCUPATION,
        re.compile(_EDUCATION_PATTERN, re.IGNORECASE),
        group=1,
        option_name="occupation",
    ),
]


def _detect_family_continuation_names(text: str) -> list[Span]:
    """Emit a PERSON span for each comma-separated continuation name (DETECT-012).

    The ``FAMILY_RELATION`` rule captures only the FIRST name after each
    relation label (``Супруга: <имя>``). A practical relation line lists
    multiple family members separated by commas
    (``дети: Иванов Пётр, Иванова Мария``); each continuation name is a
    distinct person and must become its own PERSON span so it gets its own
    token. Starting at each label match's end, walk
    :data:`_FAMILY_RELATION_CONTINUATION_RE` matches as long as they are
    anchored on a comma (semicolon / sentence end terminates the list). The
    leading capital-letter anchor in the continuation pattern keeps
    lowercase trailing common nouns out, matching the precision gate of the
    base rule.
    """
    spans: list[Span] = []
    for m in _FAMILY_RELATION_RE.finditer(text):
        pos = m.end()
        while True:
            cont = _FAMILY_RELATION_CONTINUATION_RE.match(text, pos)
            if cont is None:
                break
            spans.append(Span(cont.start(1), cont.end(1), Category.PERSON, cont.group(1)))
            pos = cont.end()
    return spans


def detect(text: str, options: object | None = None) -> list[Span]:
    """Run every regex rule, returning raw (possibly overlapping) spans.

    ``options`` gates rules with a non-``None`` ``option_name`` — a rule whose
    gating attribute is falsy on ``options`` is skipped. ``None`` keeps the
    historical behaviour (every gated rule is off — the default for opt-in
    rules), so callers that do not yet pass ``options`` see the same span list
    they always did.
    """
    spans: list[Span] = []
    for rule in RULES:
        if rule.option_name is not None and not getattr(options, rule.option_name, False):
            continue
        for m in rule.pattern.finditer(text):
            value = m.group(rule.group)
            if not value:
                continue
            if rule.validator is not None and not rule.validator(value):
                continue
            spans.append(Span(m.start(rule.group), m.end(rule.group), rule.category, value))
    # DETECT-012 continuation pass: when the family-relations option is on the
    # FAMILY_RELATION rule has already captured the first name after each
    # label; scan forward for any comma-separated trailing names that share
    # the same label scope and emit them as additional PERSON spans.
    if getattr(options, "family_relations", False):
        spans.extend(_detect_family_continuation_names(text))
    return spans
