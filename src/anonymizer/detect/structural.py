"""Document-shape-aware suppression logic for Markdown résumé documents.

Résumé-specific logic isolated here per ADR-0007: skill-section suppression
depends on the document being Markdown with ATX headers. Future document-type
suppressions (fenced code blocks, table cells, etc.) should land here too.
"""

from __future__ import annotations

import re

from anonymizer.detect.dictionaries import load as _load_dict

# Résumé-specific dictionary lists.
RESUME_FIELD_LABELS = _load_dict("resume_field_labels")
RESUME_SECTION_HEADERS = _load_dict("resume_section_headers")
RESUME_SKILL_SECTION_STEMS = _load_dict("resume_skill_section_stems")

# A markdown ATX header line: leading #'s (depth), then the heading text.
_HEADER_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def skill_section_ranges(text: str) -> list[tuple[int, int]]:
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


def is_in_any_range(start: int, ranges: list[tuple[int, int]]) -> bool:
    """True if ``start`` falls within any of the given ``[lo, hi)`` ranges."""
    return any(lo <= start < hi for lo, hi in ranges)
