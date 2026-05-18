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


def anonymize(text: str, options: Options | None = None) -> AnonResult:
    """Anonymize ``text``, returning tokenized text and a replacement map."""
    options = options or Options()
    from anonymizer.detect import detect_all

    spans = detect_all(text, options)
    return replace_spans(text, spans)
