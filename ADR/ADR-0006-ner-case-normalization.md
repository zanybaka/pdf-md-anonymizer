# ADR-0006: Case normalization before NER detection

- Status: Accepted
- Date: 2026-05-18
- Realized by: NER-003

## Context
Natasha's NER model is trained on normal-case Russian news text and misses
ALL-CAPS entities — signature-block ФИО (`КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ`) and
unquoted company names (`ООО АСТРАЛ-СОФТ`). These leak through anonymization.
CORE-005 added an ALL-CAPS ФИО regex, and a follow-up considered a regex for
unquoted ALL-CAPS company names — but that approach needs a new precision-tuned
rule for every entity shape NER already knows.

## Decision
Normalize case before NER instead of adding per-shape regex rules. In
`detect/ner.py`, build a copy of the input where every ALL-CAPS Cyrillic word
is rewritten to Title Case (`КРУГЛОВ` → `Круглов`, `АСТРАЛ-СОФТ` →
`Астрал-Софт`); legal-form abbreviations (`ООО`, `ПАО`, …) stay uppercase so
`ООО Астрал-Софт` reads as the natural-case form Natasha was trained on. The
rewrite is **length-preserving**, so span offsets from the normalized copy
index the original text 1:1 — Natasha runs on the copy, but each span's value
is sliced from the original text and the replacement map keeps the original
casing, so `restore` stays exact.

The CORE-005 ALL-CAPS ФИО regex is kept as a precision backstop: NER is
probabilistic and may still miss a name, and regex wins over NER on overlap, so
the two layers complement each other with no double-tokenization.

## Alternatives considered
- **A regex rule per ALL-CAPS shape** — rejected: duplicates entity knowledge
  NER already has, and each rule needs its own false-positive tuning.
- **Lowercasing the whole document for NER** — rejected: Natasha relies on
  initial-capital cues to find proper nouns; lowercasing everything would hurt
  recall on already-normal-case text.

## Consequences
- ALL-CAPS PERSON/ORG/LOC are tagged by NER uniformly, with no per-shape rule.
- Offsets stay valid because the rewrite never changes string length.
- NER recall on ALL-CAPS text now depends on the model, not a regex guarantee;
  the CORE-005 patronymic-anchored ФИО regex remains as a deterministic
  backstop.
