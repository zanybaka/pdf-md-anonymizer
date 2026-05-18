# ADR-0007: Structural NER suppression for résumé skill sections

- Status: Accepted
- Date: 2026-05-18
- Realized by: NER-006

## Context
Natasha is a Russian-news NER model. On résumés it reliably mistags the
capitalized tool/technology names in a skills block as `ORG` (and sometimes
`LOC`): `Git`, `TFS`, `WASM`, `Code Review`, `Production`, `Банк`, `Вэб`, … —
none are PII. NER-004 and NER-005 absorbed these into curated stoplists, but
that is whack-a-mole: every new résumé surfaces fresh terms, each needing a
hand-added entry. A stoplist can never be complete.

The hard constraint is that real employer names — including Latin-script ones
like `Deutsche Bank`, `Aker Solutions`, `Unicum` — must keep being detected, so
a blanket "drop capitalized-Latin spans" or "drop all résumé `ORG`s" rule is
wrong.

The key observation: false positives cluster *structurally*. A résumé puts
tools in a "Навыки"/"Технологии"/"Компетенции" section and employers in an
"Опыт работы" section. The two never mix. The section a span sits in is a far
stronger signal than the span's surface form.

## Decision
Suppress `ORG`/`LOC` NER recall **inside skills/technologies/competencies
sections**, identified structurally rather than by enumerating terms.

In `detect/ner.py`, `_skill_section_ranges` scans the Markdown for ATX headers
(`#`…`######`) whose text contains a skills-block stem (`навык`, `технолог`,
`компетенц`, `инструмент`, `стек`, `skill`, `technolog`, `tool`, `stack`,
`competenc`). Each such section runs from its header to the next header of the
same or shallower depth (or end of text). A detected `ORG` or `LOC` span whose
start offset falls inside any such range is dropped. `PERSON` is left on — a
name in a skills block is unusual but would still be PII.

The NER-004/NER-005 stoplists are kept as a precision backstop: they still
catch tool names that appear *outside* a recognized skills section (inline
prose, an unheadered list).

## Alternatives considered
- **Keep extending the stoplists (status quo)** — rejected as the primary
  mechanism: unbounded maintenance, never complete, and each new résumé leaks
  until patched. Retained only as a backstop.
- **Context scoring per span** (list-item density, absence of legal-form/quote
  markers, short capitalized-Latin token length) — rejected: a tunable scorer
  with no clear threshold, harder to reason about, and it risks dropping a real
  short-name employer (`Unicum`) that scores like a tool. The section signal is
  binary, explainable, and does not depend on the span's surface form.
- **Blanket drop of résumé `ORG`/`LOC`** — rejected: erases real employers,
  which are core PII for this tool.

## Consequences
- Skill-section tool false positives are suppressed wholesale, with no per-term
  entry — the stoplists stop growing for this class of leak.
- Precision on real employers is preserved: they sit in the experience
  section, which no stem matches.
- The mechanism depends on the document being Markdown with ATX headers — true
  for `pdf2md` output (the only PDF path) and for typical `.md` input. A skills
  block with no header, or one introduced by bold text only, is not recognized;
  the stoplists remain the backstop there.
- A genuine organization or location named *inside* a skills section (rare —
  e.g. "опыт миграции инфраструктуры Deutsche Bank") would be missed. Accepted:
  the false-positive cost of the status quo outweighs this edge case, and the
  experience section still catches that employer's primary mention.
