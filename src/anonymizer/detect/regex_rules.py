"""Regex and dictionary detectors for structured private data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

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
    return sum(d * w for d, w in zip(digits, weights)) % 11 % 10


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
    total = sum(x * w for x, w in zip(d[:9], _SNILS_WEIGHTS))
    if total > 101:
        total %= 101
    control = 0 if total in (100, 101) else total
    return control == d[9] * 10 + d[10]


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
_ORG_PATTERN = (
    r"\b(?:" + _ORG_ALT + r')\s*[«"“][^»"”]+[»"”]'
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
_PERSON_PATTERN = (
    r"\b[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]*" + _PATRONYMIC + r"\b"
)

# Alternation of known URL top-level domains for the scheme-less bare-domain
# branch of the URL rule (the TLD list itself lives in dictionaries/url_tlds).
_URL_TLD = "|".join(URL_TLDS)

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
    Rule("URL", Category.URL, re.compile(
        r"https?://[^\s<>()\[\]«»]+"
        r"|www\.[^\s<>()\[\]«»]+"
        r"|\b(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+(?:" + _URL_TLD + r")\b"
        r"(?:/[^\s<>()\[\]«»]*)?",
        re.IGNORECASE)),
    Rule("SECRET_PEM", Category.SECRET, re.compile(
        r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.DOTALL)),
    Rule("SECRET_KEY_VALUE", Category.SECRET, re.compile(
        r"(?:password|passwd|pwd|api[_\-]?key|apikey|secret|token|access[_\-]?key)"
        r"\s*[=:]\s*(\S+)", re.IGNORECASE), group=1),
    # Certificate serial: a "№"-prefixed run of 20+ uppercase hex characters.
    # The high-entropy SECRET rule requires mixed case, so an all-caps hex
    # serial slips past it; the "№" anchor keeps this rule from over-matching.
    Rule("SECRET_HEX_SERIAL", Category.SECRET, re.compile(r"№\s*([0-9A-F]{20,})\b"), group=1),
    Rule("ORG", Category.ORG, re.compile(_ORG_PATTERN, re.IGNORECASE)),
    Rule("PASSPORT_LABELED", Category.PASSPORT,
         re.compile(r"паспорт[:\s]*(\d{4}\s?\d{6})", re.IGNORECASE), group=1),
    Rule("PASSPORT_ISSUE_DATE", Category.PASSPORT, re.compile(
        r"(?:дата выдачи)[:\s]*(\d{2}[./]\d{2}[./]\d{4})", re.IGNORECASE), group=1),
    Rule("PASSPORT_DEPT_CODE", Category.PASSPORT, re.compile(
        r"код подразделения[:\s]*(\d{3}-\d{3})", re.IGNORECASE), group=1),
    Rule("PASSPORT_ISSUER", Category.PASSPORT, re.compile(
        r"(?:кем выдан|орган выдачи)[:\s]*([^\n]+)", re.IGNORECASE), group=1),
    # Label-anchored: requires a colon after the (optionally qualified) "адрес"
    # label, so plural "адреса средств …" is not mistaken for an address.
    Rule("ADDRESS_LABELED", Category.ADDRESS, re.compile(
        r"\bадрес\w*(?:\s+[А-Яа-яёЁ]+){0,2}\s*:\s*([^\n]+)",
        re.IGNORECASE), group=1),
    Rule("ADDRESS_INLINE", Category.ADDRESS, re.compile(
        r"\bг\.\s?[А-ЯЁ][^\n,]*(?:,\s*(?:ул|улица|пер|просп|пр-?кт|пр-?т|д|дом"
        r"|кв|корп|стр|оф)\.?\s?[^\n,]+)+", re.IGNORECASE)),
    Rule("SNILS_LABELED", Category.SNILS, re.compile(
        r"СНИЛС[:\s]*(\d{3}-\d{3}-\d{3}[\s\-]\d{2})", re.IGNORECASE),
        group=1, validator=_snils_ok),
    Rule("SNILS_BARE", Category.SNILS,
         re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[\s\-]\d{2}(?!\d)"),
         validator=_snils_ok),
    Rule("INN_LABELED", Category.INN,
         re.compile(r"ИНН[:\s]*(\d{10}(?:\d{2})?)(?!\d)", re.IGNORECASE),
         group=1, validator=_inn_ok),
    Rule("KPP", Category.KPP, re.compile(r"КПП[:\s]*(\d{9})(?!\d)", re.IGNORECASE), group=1),
    Rule("BIK", Category.BIK, re.compile(r"БИК[:\s]*(\d{9})(?!\d)", re.IGNORECASE), group=1),
    Rule("OGRNIP_LABELED", Category.OGRNIP,
         re.compile(r"ОГРНИП[:\s]*(\d{15})(?!\d)", re.IGNORECASE),
         group=1, validator=_ogrnip_ok),
    Rule("OGRNIP_BARE", Category.OGRNIP,
         re.compile(r"(?<!\d)\d{15}(?!\d)"), validator=_ogrnip_ok),
    Rule("OGRN_LABELED", Category.OGRN,
         re.compile(r"ОГРН[:\s]*(\d{13})(?!\d)", re.IGNORECASE),
         group=1, validator=_ogrn_ok),
    Rule("OGRN_BARE", Category.OGRN,
         re.compile(r"(?<!\d)\d{13}(?!\d)"), validator=_ogrn_ok),
    # Bare INN — a label-free 10- or 12-digit run, made safe only by the
    # checksum gate (DETECT-002). Ordered after the label-anchored INN and the
    # bare OGRN/OGRNIP rules so those win ties during overlap resolution. The
    # 13/15-digit OGRN/OGRNIP runs cannot match here: the `(?!\d)` boundary
    # rejects a 10/12-digit prefix of a longer digit run.
    Rule("INN_BARE", Category.INN,
         re.compile(r"(?<!\d)(?:\d{12}|\d{10})(?!\d)"),
         validator=_inn_ok),
    Rule("ACCOUNT_LABELED", Category.ACCOUNT, re.compile(
        r"(?:расч[её]тный сч[её]т|р/сч|р/с|к/с|сч[её]т|сч\.)[:\s№N]*(\d{20})(?!\d)",
        re.IGNORECASE), group=1),
    Rule("ACCOUNT_BARE", Category.ACCOUNT, re.compile(r"(?<!\d)\d{20}(?!\d)")),
    Rule("CARD", Category.CARD, re.compile(
        r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)"), validator=_luhn_ok),
    Rule("PHONE", Category.PHONE, re.compile(
        r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)")),
    Rule("PASSPORT_BARE", Category.PASSPORT, re.compile(r"(?<!\d)\d{4}\s\d{6}(?!\d)")),
    Rule("POSTAL_CODE", Category.POSTAL_CODE, re.compile(
        r"(?:почтовый индекс|индекс)[:\s]*(\d{6})(?!\d)", re.IGNORECASE), group=1),
    # DOB is label-anchored only: a bare date carries no birth-date meaning, so
    # only dates next to "дата рождения" / "д.р." / "родился"/"родилась" are
    # tokenized. The date may be numeric (ДД.ММ.ГГГГ, ГГГГ-ММ-ДД) or written
    # with a Russian month name ("16 января 1983").
    Rule("DOB", Category.DOB, re.compile(
        r"(?:дата рождения|д[./]р[.:]?|родил(?:ся|ась))[:\s]*"
        r"(\d{2}[./]\d{2}[./]\d{4}|\d{4}-\d{2}-\d{2}"
        r"|\d{1,2}\s+[а-яё]+\s+\d{4})",
        re.IGNORECASE), group=1),
    Rule("IP_V4", Category.IP, re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    Rule("IP_V6", Category.IP, re.compile(_IPV6, re.VERBOSE), group=1),
    Rule("PERSON", Category.PERSON, re.compile(_PERSON_PATTERN, re.IGNORECASE)),
    Rule("SECRET_HIGH_ENTROPY", Category.SECRET, re.compile(
        r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])"
        r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{24,}(?![A-Za-z0-9])")),
]


def detect(text: str) -> list[Span]:
    """Run every regex rule, returning raw (possibly overlapping) spans."""
    spans: list[Span] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            value = m.group(rule.group)
            if not value:
                continue
            if rule.validator is not None and not rule.validator(value):
                continue
            spans.append(Span(m.start(rule.group), m.end(rule.group),
                              rule.category, value))
    return spans
