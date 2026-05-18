# ADR-0003: Detection ordering — regex before NER

- Status: Accepted
- Date: 2026-05-18
- Realized by: NER-001

## Context
Two detection layers exist: high-precision regex/dictionary rules and Natasha
NER. They can produce overlapping matches for the same text. The TECHSPEC
recorded an `ADR-CANDIDATE` for the ordering policy; NER-001 realizes it.

## Decision
Run regex/dictionary rules first and resolve overlaps among them (earlier start
wins, longer wins on a tie). Then run NER, and keep an NER span only when it
does not overlap any regex span. Structured identifiers (INN, phone, account,
etc.) are therefore never relabeled as PERSON/ORG/LOC.

## Alternatives considered
- **NER first, regex fills gaps** — rejected: NER would mislabel unambiguous
  structured identifiers.
- **Position-only greedy merge across both layers** — rejected: an earlier NER
  span could win over a regex match, violating regex precedence.

## Consequences
- Regex precision is preserved; NER only adds names/entities in unclaimed text.
- A value caught by both layers keeps its regex category.
