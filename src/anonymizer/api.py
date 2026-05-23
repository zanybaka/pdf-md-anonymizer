"""Core entrypoint: :func:`anonymize`."""

from __future__ import annotations

from dataclasses import dataclass

from anonymizer.replace import AnonResult, replace_spans


@dataclass
class Options:
    """Detection options for :func:`anonymize`."""

    ner_org: bool = True
    ner_loc: bool = True
    llm: bool = False
    consistency_sweep: bool = True
    # Extend the NER POS filter to ORG/LOC spans (NER-007): drop a span built
    # purely from common-noun-class words. On by default (PRD maximum-removal
    # intent); turn off to keep ORG/LOC recall maximal on structured documents.
    ner_pos_filter: bool = True
    # Brand short-name propagation (DETECT-007): narrow a legal-form ORG span
    # ("ООО «Альфа-Бета»") to the inner company short-name and propagate that
    # short-name to every later bare mention. On by default — Natasha alone
    # misses short/decapitalised/unquoted repeats often enough to leak the
    # brand.
    brand_propagation: bool = True
    # Opt-in biometric-mention detection (DETECT-009): tokenize surface-text
    # descriptors like «отпечаток пальца», «голосовой отпечаток», «ДНК»,
    # «биометрические данные». Off by default — the mention itself is
    # descriptive, not identifying, so enabling it expands the redaction
    # surface beyond strict identifier removal.
    biometric_mentions: bool = False
    # Opt-in family-relation label detection (DETECT-012): tokenize the
    # capitalised names of family members listed after a Russian relation
    # label («Супруга: …», «дети: …»). The names are PERSON; the relation
    # noun itself stays in the document. Off by default — the rule is
    # broader than the existing label-anchored identifier rules and would
    # tokenise informal capitalised follow-ons in non-PII documents.
    family_relations: bool = False
    # Opt-in job-title / education-qualification detection (DETECT-013):
    # tokenize the free-text role / qualification value listed after a
    # Russian résumé label («Должность: …», «Образование: …», «Квалификация:
    # …», «Учёная степень: …»). The captured value is `Category.OCCUPATION`;
    # the label noun itself stays in the document. Off by default — the
    # capture is broader than the existing label-anchored identifier rules
    # (anything up to the next punctuation terminator), so a non-résumé
    # document with a stray «должность» label would inflate the redaction
    # surface. Free-text usages without a colon («работаю программистом»)
    # are missed by design.
    occupation: bool = False


def anonymize(text: str, options: Options | None = None) -> AnonResult:
    """Anonymize ``text``, returning tokenized text and a replacement map."""
    options = options or Options()
    from anonymizer.detect import detect_all

    spans = detect_all(text, options)
    return replace_spans(text, spans)
